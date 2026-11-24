/**
 * 零依赖离线 QR Code 编码器（Byte 模式，自动选择 Version 1-10，纠错等级 M）。
 * 暴露全局函数：window.drawQRCode(canvas, text, size)
 */
(function (global) {
  const EXP = new Uint8Array(512);
  const LOG = new Uint8Array(256);
  let x = 1;
  for (let i = 0; i < 255; i++) {
    EXP[i] = x;
    LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];

  function gfMul(a, b) {
    return a === 0 || b === 0 ? 0 : EXP[LOG[a] + LOG[b]];
  }

  function rsGenerator(degree) {
    let poly = [1];
    for (let i = 0; i < degree; i++) {
      const next = new Array(poly.length + 1).fill(0);
      const factor = EXP[i];
      for (let j = 0; j < poly.length; j++) {
        next[j] ^= poly[j];
        next[j + 1] ^= gfMul(poly[j], factor);
      }
      poly = next;
    }
    return poly;
  }

  function rsCompute(data, ecLen) {
    const gen = rsGenerator(ecLen);
    const res = new Uint8Array(data.length + ecLen);
    res.set(data);
    for (let i = 0; i < data.length; i++) {
      const coef = res[i];
      if (coef !== 0) {
        for (let j = 0; j < gen.length; j++) {
          res[i + j] ^= gfMul(gen[j], coef);
        }
      }
    }
    return res.slice(data.length);
  }

  // Version 1..10, EC Level M: [totalCodewords, ecPerBlock, blocksG1, dataG1, blocksG2, dataG2, alignPos[]]
  const VERSIONS = [
    null,
    [26, 10, 1, 16, 0, 0, []],
    [44, 16, 1, 28, 0, 0, [6, 18]],
    [70, 26, 1, 44, 0, 0, [6, 22]],
    [100, 18, 2, 32, 0, 0, [6, 26]],
    [134, 24, 2, 43, 0, 0, [6, 30]],
    [172, 16, 4, 27, 0, 0, [6, 34]],
    [196, 18, 4, 31, 0, 0, [6, 22, 38]],
    [242, 22, 2, 38, 2, 39, [6, 24, 42]],
    [292, 22, 3, 36, 2, 37, [6, 26, 46]],
    [346, 26, 4, 43, 1, 44, [6, 28, 50]],
  ];

  // Format info for EC Level M (00) + mask 0..7
  const FORMAT_INFO_M = [
    0x5412, 0x5125, 0x5e7c, 0x5b4b, 0x45f9, 0x40ce, 0x4f97, 0x4aa0,
  ];
  // Version info for Version 7..10
  const VERSION_INFO = {
    7: 0x07c94, 8: 0x085bc, 9: 0x09a99, 10: 0x0a4d3,
  };

  function encodeQR(text) {
    const bytes = new TextEncoder().encode(text);
    let ver = 0;
    for (let v = 1; v < VERSIONS.length; v++) {
      const cfg = VERSIONS[v];
      const dataCap = cfg[2] * cfg[3] + cfg[4] * cfg[5];
      const headerBytes = v >= 10 ? 3 : 2; // 4bit mode + 8/16bit len
      if (bytes.length + headerBytes <= dataCap) {
        ver = v;
        break;
      }
    }
    if (!ver) throw new Error('文本过长（当前离线版支持最多约 210 字节）');

    const cfg = VERSIONS[ver];
    const [totalCw, ecPerBlock, b1, d1, b2, d2, align] = cfg;
    const dataCap = b1 * d1 + b2 * d2;

    // 构造比特流
    const bits = [];
    const pushBits = (val, len) => {
      for (let i = len - 1; i >= 0; i--) bits.push((val >> i) & 1);
    };
    pushBits(0b0100, 4); // Byte mode
    pushBits(bytes.length, ver >= 10 ? 16 : 8);
    for (const b of bytes) pushBits(b, 8);
    const maxBits = dataCap * 8;
    for (let i = 0; i < 4 && bits.length < maxBits; i++) bits.push(0);
    while (bits.length % 8 !== 0) bits.push(0);
    const pads = [0xec, 0x11];
    let padIdx = 0;
    while (bits.length < maxBits) {
      pushBits(pads[padIdx++ & 1], 8);
    }

    const dataCw = new Uint8Array(dataCap);
    for (let i = 0; i < dataCap; i++) {
      let b = 0;
      for (let j = 0; j < 8; j++) b = (b << 1) | bits[i * 8 + j];
      dataCw[i] = b;
    }

    // 分块并生成纠错码
    const dataBlocks = [];
    const ecBlocks = [];
    let offset = 0;
    for (let i = 0; i < b1; i++) {
      const blk = dataCw.slice(offset, offset + d1);
      offset += d1;
      dataBlocks.push(blk);
      ecBlocks.push(rsCompute(blk, ecPerBlock));
    }
    for (let i = 0; i < b2; i++) {
      const blk = dataCw.slice(offset, offset + d2);
      offset += d2;
      dataBlocks.push(blk);
      ecBlocks.push(rsCompute(blk, ecPerBlock));
    }

    // 交错数据与纠错码
    const finalCw = [];
    const maxD = Math.max(d1, d2);
    for (let i = 0; i < maxD; i++) {
      for (const blk of dataBlocks) if (i < blk.length) finalCw.push(blk[i]);
    }
    for (let i = 0; i < ecPerBlock; i++) {
      for (const blk of ecBlocks) finalCw.push(blk[i]);
    }

    // 初始化矩阵
    const n = ver * 4 + 17;
    const mat = Array.from({ length: n }, () => new Int8Array(n).fill(-1));
    const isFunc = Array.from({ length: n }, () => new Uint8Array(n));

    const setMod = (r, c, val, func = true) => {
      if (r < 0 || r >= n || c < 0 || c >= n) return;
      mat[r][c] = val ? 1 : 0;
      if (func) isFunc[r][c] = 1;
    };

    const drawFinder = (r0, c0) => {
      for (let dr = -1; dr <= 7; dr++) {
        for (let dc = -1; dc <= 7; dc++) {
          const inOuter = dr >= 0 && dr <= 6 && dc >= 0 && dc <= 6;
          const border = dr === 0 || dr === 6 || dc === 0 || dc === 6;
          const center = dr >= 2 && dr <= 4 && dc >= 2 && dc <= 4;
          setMod(r0 + dr, c0 + dc, inOuter && (border || center));
        }
      }
    };
    drawFinder(0, 0);
    drawFinder(0, n - 7);
    drawFinder(n - 7, 0);

    // 定位定时线
    for (let i = 8; i < n - 8; i++) {
      setMod(6, i, i % 2 === 0);
      setMod(i, 6, i % 2 === 0);
    }

    // 对齐图形
    for (const r of align) {
      for (const c of align) {
        if (isFunc[r][c]) continue;
        for (let dr = -2; dr <= 2; dr++) {
          for (let dc = -2; dc <= 2; dc++) {
            const d = Math.max(Math.abs(dr), Math.abs(dc));
            setMod(r + dr, c + dc, d === 0 || d === 2);
          }
        }
      }
    }

    // 预留格式区与暗模块
    for (let i = 0; i < 9; i++) {
      if (i !== 6) {
        isFunc[8][i] = 1;
        isFunc[i][8] = 1;
      }
    }
    for (let i = 0; i < 8; i++) {
      isFunc[8][n - 1 - i] = 1;
      isFunc[n - 1 - i][8] = 1;
    }
    setMod(n - 8, 8, 1);

    // 版本信息 (v >= 7)
    if (ver >= 7) {
      const vinfo = VERSION_INFO[ver];
      for (let i = 0; i < 18; i++) {
        const bit = (vinfo >> i) & 1;
        const a = Math.floor(i / 3);
        const b = n - 11 + (i % 3);
        setMod(a, b, bit);
        setMod(b, a, bit);
      }
    }

    // 填充数据位
    let bitIdx = 0;
    const totalBits = finalCw.length * 8;
    let upward = true;
    for (let col = n - 1; col > 0; col -= 2) {
      if (col === 6) col--;
      for (let step = 0; step < n; step++) {
        const row = upward ? n - 1 - step : step;
        for (let dc = 0; dc < 2; dc++) {
          const c = col - dc;
          if (!isFunc[row][c]) {
            const bit = bitIdx < totalBits ? (finalCw[bitIdx >> 3] >> (7 - (bitIdx & 7))) & 1 : 0;
            bitIdx++;
            mat[row][c] = bit;
          }
        }
      }
      upward = !upward;
    }

    // 使用 Mask 0 ((r + c) % 2 === 0) 并写入格式信息
    const maskId = 0;
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) {
        if (!isFunc[r][c] && ((r + c) % 2 === 0)) mat[r][c] ^= 1;
      }
    }
    const fmt = FORMAT_INFO_M[maskId];
    const fmtCoords1 = [
      [8, 0], [8, 1], [8, 2], [8, 3], [8, 4], [8, 5], [8, 7], [8, 8],
      [7, 8], [5, 8], [4, 8], [3, 8], [2, 8], [1, 8], [0, 8],
    ];
    const fmtCoords2 = [
      [n - 1, 8], [n - 2, 8], [n - 3, 8], [n - 4, 8], [n - 5, 8], [n - 6, 8], [n - 7, 8],
      [8, n - 8], [8, n - 7], [8, n - 6], [8, n - 5], [8, n - 4], [8, n - 3], [8, n - 2], [8, n - 1],
    ];
    for (let i = 0; i < 15; i++) {
      const bit = (fmt >> (14 - i)) & 1;
      mat[fmtCoords1[i][0]][fmtCoords1[i][1]] = bit;
      mat[fmtCoords2[i][0]][fmtCoords2[i][1]] = bit;
    }
    return mat;
  }

  global.drawQRCode = function (canvas, text, size) {
    const mat = encodeQR(text);
    const n = mat.length;
    const margin = 2;
    const scale = Math.max(3, Math.floor((size || 240) / (n + margin * 2)));
    const dim = (n + margin * 2) * scale;
    canvas.width = dim;
    canvas.height = dim;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, dim, dim);
    ctx.fillStyle = '#111827';
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) {
        if (mat[r][c] === 1) {
          ctx.fillRect((c + margin) * scale, (r + margin) * scale, scale, scale);
        }
      }
    }
  };
})(window);

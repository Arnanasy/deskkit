"""DeskKit 系统托盘图标（纯标准库 Win32 API，零第三方依赖）。

功能：
- 左键单击：在默认浏览器打开 DeskKit 本地页面
- 右键菜单：打开工具箱网页 / 打开输出文件夹 / 退出后台服务
- 自动恢复：Windows 资源管理器重启后自动重新挂载托盘图标
"""
import ctypes
from ctypes import wintypes
from pathlib import Path

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
shell32 = ctypes.WinDLL('shell32', use_last_error=True)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_TRAY = WM_APP + 10

NIM_ADD = 0x00
NIM_DELETE = 0x02
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04

TPM_RIGHTBUTTON = 0x0002
TPM_NONOTIFY = 0x0080
TPM_RETURNCMD = 0x0100
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
SM_CXSMICON = 49
SM_CYSMICON = 50
NULL_PEN = 8

IDM_OPEN = 3001
IDM_FOLDER = 3002
IDM_QUIT = 3003


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ('style', wintypes.UINT),
        ('lpfnWndProc', WNDPROC),
        ('cbClsExtra', ctypes.c_int),
        ('cbWndExtra', ctypes.c_int),
        ('hInstance', wintypes.HINSTANCE),
        ('hIcon', wintypes.HICON),
        ('hCursor', wintypes.HANDLE),
        ('hbrBackground', wintypes.HBRUSH),
        ('lpszMenuName', wintypes.LPCWSTR),
        ('lpszClassName', wintypes.LPCWSTR),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ('fIcon', wintypes.BOOL),
        ('xHotspot', wintypes.DWORD),
        ('yHotspot', wintypes.DWORD),
        ('hbmMask', wintypes.HBITMAP),
        ('hbmColor', wintypes.HBITMAP),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('hWnd', wintypes.HWND),
        ('uID', wintypes.UINT),
        ('uFlags', wintypes.UINT),
        ('uCallbackMessage', wintypes.UINT),
        ('hIcon', wintypes.HICON),
        ('szTip', wintypes.WCHAR * 128),
        ('dwState', wintypes.DWORD),
        ('dwStateMask', wintypes.DWORD),
        ('szInfo', wintypes.WCHAR * 256),
        ('uVersion', wintypes.UINT),
        ('szInfoTitle', wintypes.WCHAR * 64),
        ('dwInfoFlags', wintypes.DWORD),
        ('guidItem', wintypes.BYTE * 16),
        ('hBalloonIcon', wintypes.HICON),
    ]


def _sig(fn, restype, *argtypes):
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


_sig(kernel32.GetModuleHandleW, wintypes.HMODULE, wintypes.LPCWSTR)
_sig(user32.RegisterClassW, wintypes.ATOM, ctypes.POINTER(WNDCLASSW))
_sig(user32.CreateWindowExW, wintypes.HWND, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
     wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
     wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
_sig(user32.DefWindowProcW, LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)
_sig(user32.DestroyWindow, wintypes.BOOL, wintypes.HWND)
_sig(user32.PostQuitMessage, None, ctypes.c_int)
_sig(user32.PostMessageW, wintypes.BOOL, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)
_sig(user32.GetMessageW, wintypes.BOOL, ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
_sig(user32.TranslateMessage, wintypes.BOOL, ctypes.POINTER(wintypes.MSG))
_sig(user32.DispatchMessageW, LRESULT, ctypes.POINTER(wintypes.MSG))
_sig(user32.RegisterWindowMessageW, wintypes.UINT, wintypes.LPCWSTR)
_sig(user32.GetCursorPos, wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
_sig(user32.SetForegroundWindow, wintypes.BOOL, wintypes.HWND)
_sig(user32.CreatePopupMenu, wintypes.HMENU)
_sig(user32.AppendMenuW, wintypes.BOOL, wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR)
_sig(user32.TrackPopupMenu, wintypes.BOOL, wintypes.HMENU, wintypes.UINT,
     ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.LPVOID)
_sig(user32.DestroyMenu, wintypes.BOOL, wintypes.HMENU)
_sig(user32.LoadImageW, wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPCWSTR,
     wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT)
_sig(user32.GetSystemMetrics, ctypes.c_int, ctypes.c_int)
_sig(user32.CreateIconIndirect, wintypes.HICON, ctypes.POINTER(ICONINFO))
_sig(user32.DestroyIcon, wintypes.BOOL, wintypes.HICON)
_sig(user32.GetDC, wintypes.HDC, wintypes.HWND)
_sig(user32.ReleaseDC, ctypes.c_int, wintypes.HWND, wintypes.HDC)

_sig(gdi32.GetStockObject, wintypes.HGDIOBJ, ctypes.c_int)
_sig(gdi32.CreateCompatibleDC, wintypes.HDC, wintypes.HDC)
_sig(gdi32.CreateCompatibleBitmap, wintypes.HBITMAP, wintypes.HDC, ctypes.c_int, ctypes.c_int)
_sig(gdi32.CreateBitmap, wintypes.HBITMAP, ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, wintypes.LPVOID)
_sig(gdi32.SelectObject, wintypes.HGDIOBJ, wintypes.HDC, wintypes.HGDIOBJ)
_sig(gdi32.CreateSolidBrush, wintypes.HBRUSH, wintypes.COLORREF)
_sig(gdi32.RoundRect, wintypes.BOOL, wintypes.HDC, ctypes.c_int, ctypes.c_int,
     ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)
_sig(gdi32.Rectangle, wintypes.BOOL, wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)
_sig(gdi32.DeleteObject, wintypes.BOOL, wintypes.HGDIOBJ)
_sig(gdi32.DeleteDC, wintypes.BOOL, wintypes.HDC)

_sig(shell32.Shell_NotifyIconW, wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW))


def _make_toolbox_icon():
    """用 GDI 绘制圆角蓝色背景 + 白色小工具箱图标（无外部 ico 文件时使用）。"""
    size = 32
    screen_dc = user32.GetDC(None)
    color_bmp = gdi32.CreateCompatibleBitmap(screen_dc, size, size)
    mask_bits = ctypes.create_string_buffer(((size + 15) // 16) * 2 * size)
    mask_bmp = gdi32.CreateBitmap(size, size, 1, 1, mask_bits)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    old_bmp = gdi32.SelectObject(mem_dc, color_bmp)
    old_pen = gdi32.SelectObject(mem_dc, gdi32.GetStockObject(NULL_PEN))

    blue = gdi32.CreateSolidBrush(0x00EB6325)   # #2563EB (BGR)
    white = gdi32.CreateSolidBrush(0x00FFFFFF)
    old_brush = gdi32.SelectObject(mem_dc, blue)
    gdi32.RoundRect(mem_dc, 0, 0, size, size, 9, 9)

    # 白色工具箱提手与箱体
    gdi32.SelectObject(mem_dc, white)
    gdi32.Rectangle(mem_dc, 11, 6, 21, 11)
    gdi32.SelectObject(mem_dc, blue)
    gdi32.Rectangle(mem_dc, 13, 8, 19, 11)
    gdi32.SelectObject(mem_dc, white)
    gdi32.Rectangle(mem_dc, 6, 11, 26, 25)
    # 中间分隔条与锁扣
    gdi32.SelectObject(mem_dc, blue)
    gdi32.Rectangle(mem_dc, 6, 16, 26, 18)
    gdi32.SelectObject(mem_dc, white)
    gdi32.Rectangle(mem_dc, 14, 15, 18, 19)

    gdi32.SelectObject(mem_dc, old_brush)
    gdi32.SelectObject(mem_dc, old_pen)
    gdi32.SelectObject(mem_dc, old_bmp)

    info = ICONINFO(fIcon=True, hbmMask=mask_bmp, hbmColor=color_bmp)
    hicon = user32.CreateIconIndirect(ctypes.byref(info))

    user32.ReleaseDC(None, screen_dc)
    gdi32.DeleteDC(mem_dc)
    for obj in (color_bmp, mask_bmp, blue, white):
        gdi32.DeleteObject(obj)
    return hicon


class DeskKitTray:
    def __init__(self, tip, on_open, on_folder, icon_path=None):
        self.tip = tip[:120]
        self.on_open = on_open
        self.on_folder = on_folder
        self.icon_path = Path(icon_path) if icon_path else None
        self.hwnd = None
        self._hicon = None
        self._proc_ref = WNDPROC(self._wndproc)
        self._taskbar_created = user32.RegisterWindowMessageW('TaskbarCreated')

    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        return nid

    def _add_icon(self):
        nid = self._nid()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._hicon
        nid.szTip = self.tip
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _remove_icon(self):
        if self.hwnd:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid()))

    def _show_menu(self):
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, IDM_OPEN, '打开 DeskKit 工具箱')
        user32.AppendMenuW(menu, MF_STRING, IDM_FOLDER, '打开输出文件夹')
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, IDM_QUIT, '退出后台服务')
        user32.SetForegroundWindow(self.hwnd)
        cmd = 0
        try:
            cmd = user32.TrackPopupMenu(
                menu, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD,
                pt.x, pt.y, 0, self.hwnd, None,
            )
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(menu)
        if cmd == IDM_OPEN:
            self.on_open()
        elif cmd == IDM_FOLDER:
            self.on_folder()
        elif cmd == IDM_QUIT:
            self.request_quit()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if self._taskbar_created and msg == self._taskbar_created:
            self._add_icon()
            return 0
        if msg == WM_TRAY:
            mouse = lparam & 0xFFFF
            if mouse == WM_LBUTTONUP:
                self.on_open()
                return 0
            if mouse == WM_RBUTTONUP:
                self._show_menu()
                return 0
        if msg == WM_CLOSE:
            self._remove_icon()
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def request_quit(self):
        """线程安全地请求托盘退出消息循环（可从 HTTP 线程调用）。"""
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def run(self):
        hinst = kernel32.GetModuleHandleW(None)
        cls_name = 'DeskKitTrayHiddenWnd'
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc_ref
        wc.hInstance = hinst
        wc.lpszClassName = cls_name
        user32.RegisterClassW(ctypes.byref(wc))

        self.hwnd = user32.CreateWindowExW(
            0, cls_name, 'DeskKit', 0, 0, 0, 0, 0, None, None, hinst, None,
        )
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        if self.icon_path and self.icon_path.is_file():
            self._hicon = user32.LoadImageW(
                None, str(self.icon_path), IMAGE_ICON,
                user32.GetSystemMetrics(SM_CXSMICON),
                user32.GetSystemMetrics(SM_CYSMICON),
                LR_LOADFROMFILE,
            )
        if not self._hicon:
            self._hicon = _make_toolbox_icon()

        self._add_icon()
        try:
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._remove_icon()
            if self._hicon:
                user32.DestroyIcon(self._hicon)
                self._hicon = None
            self.hwnd = None

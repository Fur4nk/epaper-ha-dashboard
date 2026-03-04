import inspect
import os
import sys


def resolve_epd_lib_path(custom_path: str, script_dir: str):
    env_path = os.environ.get("EPD_LIB_PATH", "")
    candidate_paths = [
        custom_path,
        env_path,
        os.path.expanduser("~/e-Paper/RaspberryPi_JetsonNano/python/lib"),
        os.path.expanduser("~/src/e-Paper/RaspberryPi_JetsonNano/python/lib"),
        os.path.abspath(os.path.join(script_dir, "..", "e-Paper", "RaspberryPi_JetsonNano", "python", "lib")),
    ]
    normalized = []
    seen = set()
    for p in candidate_paths:
        if not p:
            continue
        ap = os.path.abspath(os.path.expanduser(p))
        if ap not in seen:
            normalized.append(ap)
            seen.add(ap)
    epd_path = next((p for p in normalized if os.path.isdir(p)), None)
    return epd_path, normalized


def load_epd_driver(epd_lib_path: str, script_dir: str, log):
    epd_path, checked_paths = resolve_epd_lib_path(epd_lib_path, script_dir)
    if epd_path and epd_path not in sys.path:
        sys.path.insert(0, epd_path)
    try:
        from waveshare_epd import epd7in5_V2 as epd_driver
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "waveshare_epd not found. Checked paths: "
            + ", ".join(checked_paths)
            + ". Set EPD_LIB_PATH or use --epd-lib-path."
        ) from e
    log.info(f"Using Waveshare library path: {epd_path}")
    return epd_driver


def first_callable(obj, names):
    for name in names:
        fn = getattr(obj, name, None)
        if callable(fn):
            return fn, name
    return None, None


def align_rect_for_epd(rect, width, height):
    x0, y0, x1, y1 = rect
    x0 = max(0, min(width - 1, x0))
    y0 = max(0, min(height - 1, y0))
    x1 = max(1, min(width, x1))
    y1 = max(1, min(height, y1))
    x0 = (x0 // 8) * 8
    x1 = min(width, ((x1 + 7) // 8) * 8)
    if x1 <= x0:
        x1 = min(width, x0 + 8)
    if y1 <= y0:
        y1 = min(height, y0 + 1)
    return x0, y0, x1, y1


def safe_partial_refresh(epd, disp_fn, buffer, rect=None):
    width = int(getattr(epd, "width", 800))
    height = int(getattr(epd, "height", 480))
    x0, y0, x1, y1 = align_rect_for_epd(rect or (0, 0, width, height), width, height)
    try:
        num_params = len(inspect.signature(disp_fn).parameters)
    except Exception:
        num_params = 0
    try:
        if num_params == 1:
            disp_fn(buffer)
            return True
        if num_params >= 5:
            try:
                disp_fn(buffer, x0, y0, x1, y1)
            except TypeError:
                disp_fn(buffer, x0, y0, x1 - 1, y1 - 1)
            return True
    except TypeError:
        return False
    return False


def partial_refresh_rects(epd, disp_fn, buffer, rects):
    for rect in rects:
        if not safe_partial_refresh(epd, disp_fn, buffer, rect=rect):
            return False
    return True


def send_to_epaper(
    img,
    epd_lib_path: str,
    mode: str,
    clock_partial_refresh: bool,
    script_dir: str,
    log,
):
    epd_driver = load_epd_driver(epd_lib_path, script_dir, log)
    log.info("Initializing e-Paper...")
    epd = epd_driver.EPD()
    img_hw = img.rotate(90, expand=True)
    buffer = epd.getbuffer(img_hw)

    if mode == "clock" and clock_partial_refresh:
        init_fn, init_name = first_callable(epd, ["init_part", "init_fast", "init_Fast", "init"])
        disp_fn, disp_name = first_callable(epd, ["displayPartial", "display_partial", "display_Partial"])
        if init_fn and disp_fn:
            init_fn()
            log.info(f"Clock refresh using partial mode ({init_name} + {disp_name})")
            if not safe_partial_refresh(epd, disp_fn, buffer, rect=None):
                log.warning("Partial signature mismatch, using full refresh for clock mode")
                epd.init()
                epd.display(buffer)
        else:
            log.warning("Partial refresh not supported by this driver, using full refresh for clock mode")
            epd.init()
            epd.display(buffer)
    elif mode == "clock":
        log.info("Clock mode using full refresh (clock_partial_refresh disabled)")
        epd.init()
        epd.display(buffer)
    else:
        epd.init()
        log.info("Refreshing display...")
        epd.display(buffer)
    log.info("Sleep mode")
    epd.sleep()

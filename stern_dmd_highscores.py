#!/usr/bin/env python3
"""Generate animated GIF highscore displays for Stern pinball machines on a 128x32 DMD."""

import argparse
import configparser
import io
import json
import math
import os
import re
import time
import urllib.request
import urllib.parse
import http.cookiejar
import ssl

from PIL import Image, ImageDraw, ImageFont

DMD_WIDTH = 128
DMD_HEIGHT = 32
DMD_COLOR_LEFT = (160, 170, 190)   # Cool silver
DMD_COLOR_RIGHT = (240, 245, 255)  # Bright silver-white

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_AVATAR = os.path.join(SCRIPT_DIR, "pinball_default.png")

CACHE_DIR = "/tmp/stern_highscores"
CACHE_FILE = os.path.join(CACHE_DIR, "cache.json")
INDEX_FILE = os.path.join(CACHE_DIR, "next_index")
IMG_CACHE_DIR = os.path.join(CACHE_DIR, "images")

# Browser-like headers used by the Stern Insider web app
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:142.0) Gecko/20100101 Firefox/142.0",
    "Accept-Language": "en-US,en;q=0.5",
    "DNT": "1",
    "Sec-GPC": "1",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}

CMS_BASE = "https://cms.prd.sternpinball.io/api/v1/portal"
API_V2_BASE = "https://api.prd.sternpinball.io/api/v2/portal"


def load_config(path):
    cfg = configparser.ConfigParser()
    cfg.read(path)
    return cfg


def _ssl_context():
    ctx = ssl.create_default_context()
    return ctx


def _load_credentials(cfg):
    """Load username/password from separate credentials file if configured."""
    creds_file = cfg.get("stern", "credentials_file", fallback=None)
    if creds_file:
        creds_path = creds_file if os.path.isabs(creds_file) else os.path.join(SCRIPT_DIR, creds_file)
        creds = configparser.ConfigParser()
        creds.read(creds_path)
        return creds.get("stern", "username"), creds.get("stern", "password")
    return cfg.get("stern", "username"), cfg.get("stern", "password")


def login(cfg):
    """Authenticate with Stern Insider via Next.js server action. Returns (token, cookies) or (None, None)."""
    url = cfg.get("api", "login_url")
    username, password = _load_credentials(cfg)

    body = json.dumps([username, password]).encode("utf-8")

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "text/plain;charset=UTF-8")
    req.add_header("Accept", "text/x-component")
    req.add_header("Referer", "https://insider.sternpinball.com/login")
    req.add_header("Origin", "https://insider.sternpinball.com")
    req.add_header("Next-Action", "9d2cf818afff9e2c69368771b521d93585a10433")
    req.add_header("Next-Router-State-Tree",
                    "%5B%22%22%2C%7B%22children%22%3A%5B%22login%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2Flogin%22%2C%22refresh%22%5D%7D%5D%7D%2Cnull%2Cnull%2Ctrue%5D")
    for k, v in BROWSER_HEADERS.items():
        req.add_header(k, v)
    req.add_header("Sec-Fetch-Dest", "empty")
    req.add_header("Sec-Fetch-Mode", "cors")
    req.add_header("Sec-Fetch-Site", "same-origin")

    resp = urllib.request.urlopen(req, timeout=30, context=_ssl_context())
    token = None
    cookies_parts = []
    for header_val in resp.headers.get_all("Set-Cookie") or []:
        cookie_part = header_val.split(";")[0]
        cookies_parts.append(cookie_part)
        m = re.search(r"spb-insider-token=([^;]+)", header_val)
        if m:
            token = m.group(1)

    cookies = "; ".join(cookies_parts)
    if token:
        return token, cookies
    return None, None


def _location_header(cfg):
    country = cfg.get("api", "location_country", fallback="DE")
    continent = cfg.get("api", "location_continent", fallback="EU")
    return json.dumps({"country": country, "continent": continent})


def api_get(url, token, cookies, cfg):
    """Make an authenticated GET request to the Stern CMS API."""
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Cookie", cookies)
    req.add_header("Location", _location_header(cfg))
    req.add_header("Accept", "application/json, text/plain, */*")
    req.add_header("Content-Type", "application/json")
    req.add_header("Referer", "https://insider.sternpinball.com/")
    req.add_header("Origin", "https://insider.sternpinball.com")
    for k, v in BROWSER_HEADERS.items():
        req.add_header(k, v)
    req.add_header("Sec-Fetch-Dest", "empty")
    req.add_header("Sec-Fetch-Mode", "cors")
    req.add_header("Sec-Fetch-Site", "cross-site")

    resp = urllib.request.urlopen(req, timeout=30, context=_ssl_context())
    return json.loads(resp.read().decode())


def fetch_machines(token, cookies, cfg):
    url = cfg.get("api", "machines_url")
    data = api_get(url, token, cookies, cfg)
    # Response: {"user": {"machines": [...]}}
    if isinstance(data, dict) and "user" in data:
        machines = data["user"].get("machines", [])
    elif isinstance(data, list):
        machines = data
    else:
        machines = []
    return [m for m in machines if not m.get("archived", False)]


def fetch_highscores(token, cookies, cfg, machine_id):
    url = cfg.get("api", "highscores_url").format(machine_id)
    data = api_get(url, token, cookies, cfg)
    # Response: {"high_score": [...]}
    if isinstance(data, dict) and "high_score" in data:
        return data["high_score"]
    if isinstance(data, list):
        return data
    return []


def fetch_avatars(token, cookies, cfg):
    """Fetch avatar map {initials_lower: {avatar_url, background_color_hex}} from user_detail V2 API."""
    url = API_V2_BASE + "/user_detail/"
    try:
        data = api_get(url, token, cookies, cfg)
    except Exception:
        return {}
    avatars = {}
    profile = (data.get("user") or {}).get("profile") or {}
    if profile.get("initials") and profile.get("avatar_url"):
        avatars[profile["initials"].lower()] = {
            "avatar_url": profile["avatar_url"],
            "background_color_hex": profile.get("background_color_hex", ""),
        }
    for f in profile.get("following") or []:
        if f.get("initials") and f.get("avatar_url"):
            avatars[f["initials"].lower()] = {
                "avatar_url": f["avatar_url"],
                "background_color_hex": f.get("background_color_hex", ""),
            }
    return avatars


def get_grand_champions(token, cookies, cfg):
    """Return list of dicts with machine info and grand champion score."""
    machines = fetch_machines(token, cookies, cfg)
    avatars = fetch_avatars(token, cookies, cfg)
    champions = []
    for m in machines:
        machine_id = m.get("id")
        # Machine name from model.title.name
        model = m.get("model") or {}
        title = model.get("title") or {}
        machine_name = title.get("name", "UNKNOWN")
        square_logo_url = title.get("square_logo", "")

        try:
            scores = fetch_highscores(token, cookies, cfg, machine_id)
        except Exception:
            continue
        if not scores:
            continue

        gc = scores[0]
        user = gc.get("user") or {}
        initials = user.get("initials", "???")
        score_val = gc.get("score", 0)

        # Find avatar for this player
        avatar_url = ""
        avatar_info = avatars.get(initials.lower())
        if avatar_info:
            avatar_url = avatar_info.get("avatar_url", "")

        champions.append({
            "name": machine_name.upper(),
            "initials": str(initials).upper(),
            "score": int(score_val),
            "logo_url": square_logo_url,
            "avatar_url": avatar_url,
        })
    return champions


def get_cached_champions(token, cookies, cfg):
    """Return champions list, using cache if fresh enough."""
    min_poll = cfg.getfloat("display", "min_poll_seconds", fallback=3000)
    os.makedirs(CACHE_DIR, exist_ok=True)

    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
        if time.time() - cache.get("timestamp", 0) < min_poll:
            return cache["champions"]

    champions = get_grand_champions(token, cookies, cfg)
    with open(CACHE_FILE, "w") as f:
        json.dump({"timestamp": time.time(), "champions": champions}, f)
    return champions


def get_next_index(count):
    """Read and advance the round-robin index."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    idx = 0
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r") as f:
                idx = int(f.read().strip())
        except (ValueError, OSError):
            idx = 0
    if idx >= count:
        idx = 0
    next_idx = (idx + 1) % count
    with open(INDEX_FILE, "w") as f:
        f.write(str(next_idx))
    return idx


def format_score(score):
    return f"{score:,}"


def download_image(url, cache_name, fallback=None):
    """Download an image from URL, cache locally, return as PIL Image or None."""
    if not url:
        if fallback and os.path.exists(fallback):
            return Image.open(fallback).convert("RGBA")
        return None
    os.makedirs(IMG_CACHE_DIR, exist_ok=True)
    # Sanitize cache name
    safe_name = re.sub(r'[^\w.-]', '_', cache_name)
    cache_path = os.path.join(IMG_CACHE_DIR, safe_name)

    if os.path.exists(cache_path):
        try:
            return Image.open(cache_path).convert("RGBA")
        except Exception:
            pass

    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", BROWSER_HEADERS["User-Agent"])
        resp = urllib.request.urlopen(req, timeout=15, context=_ssl_context())
        data = resp.read()
        with open(cache_path, "wb") as f:
            f.write(data)
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def fit_image(img, max_height):
    """Resize image to fit within max_height, keeping aspect ratio."""
    if img is None:
        return None
    w, h = img.size
    if h <= max_height:
        return img
    ratio = max_height / h
    new_w = max(1, int(w * ratio))
    return img.resize((new_w, max_height), Image.LANCZOS)


def _resolve_font_path(cfg, key):
    """Resolve a font path from config, trying the path as-is first, then relative to script dir."""
    path = cfg.get("display", key, fallback=None)
    if not path:
        return None
    if os.path.exists(path):
        return path
    alt = os.path.join(SCRIPT_DIR, path)
    if os.path.exists(alt):
        return alt
    return path  # let truetype raise if not found


def load_font(text, max_width, font_path, start_size=14, min_size=6):
    """Load font, shrinking size until text fits within max_width."""
    size = start_size
    while size >= min_size:
        try:
            font = ImageFont.truetype(font_path, size)
        except (OSError, IOError):
            return ImageFont.load_default()
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
        if tw <= max_width:
            return font
        size -= 1
    return font


def sine_ease_in(t):
    """0->1 with sine ease (slow start, fast end)."""
    return 1 - math.cos(t * math.pi / 2)


def sine_ease_out(t):
    """0->1 with sine ease (fast start, slow end)."""
    return math.sin(t * math.pi / 2)


def generate_gif(champion, cfg, output_path, force_effect=None):
    """Generate a 128x32 animated GIF with two-line layout, machine logo, and player avatar."""
    top_half = DMD_HEIGHT // 2  # 16px
    bot_half = DMD_HEIGHT - top_half  # 16px

    # Load and shrink machine logo (for top-left area)
    logo_img = download_image(champion.get("logo_url"), f"logo_{champion['name']}")
    logo_img = fit_image(logo_img, top_half)
    logo_width = logo_img.size[0] if logo_img else 0

    # Load and shrink player avatar (for bottom line, left of initials)
    avatar_img = download_image(champion.get("avatar_url"), f"avatar_{champion['initials']}",
                                fallback=DEFAULT_AVATAR)
    avatar_img = fit_image(avatar_img, bot_half)
    avatar_width = avatar_img.size[0] if avatar_img else 0

    # Resolve fonts: name_font for top line, score_font for bottom line
    name_font_path = _resolve_font_path(cfg, "name_font_path") or _resolve_font_path(cfg, "font_path")
    score_font_path = _resolve_font_path(cfg, "score_font_path") or _resolve_font_path(cfg, "font_path")

    # Top line: machine name (accounting for logo width)
    name_text = champion["name"]
    name_avail_width = DMD_WIDTH - logo_width - (2 if logo_width else 0) - 2
    name_font = load_font(name_text, name_avail_width, name_font_path, start_size=12, min_size=6)
    name_bbox = name_font.getbbox(name_text)
    name_tw = name_bbox[2] - name_bbox[0]
    name_th = name_bbox[3] - name_bbox[1]
    name_y_off = name_bbox[1]

    # Bottom line: [avatar] [initials] [score] — initials rendered separately for effects
    initials_text = champion["initials"]
    score_num_text = format_score(champion['score'])
    full_bot_text = f"{initials_text} {score_num_text}"
    bot_avail_width = DMD_WIDTH - avatar_width - 2
    score_font = load_font(full_bot_text, bot_avail_width, score_font_path, start_size=12, min_size=6)

    initials_bbox = score_font.getbbox(initials_text)
    initials_tw = initials_bbox[2] - initials_bbox[0]
    space_bbox = score_font.getbbox(initials_text + " ")
    space_after_initials = (space_bbox[2] - space_bbox[0]) - initials_tw

    full_bot_bbox = score_font.getbbox(full_bot_text)
    score_tw = full_bot_bbox[2] - full_bot_bbox[0]
    score_th = full_bot_bbox[3] - full_bot_bbox[1]
    score_y_off = full_bot_bbox[1]

    # Pick a random initials effect (0-3: heartbeat, color cycle, sparkle, flash fade)
    import random
    effect_idx = force_effect if force_effect is not None else random.randint(0, 3)

    # Compute total content width for scrolling (max of the two lines' total widths)
    top_content_w = logo_width + (2 if logo_width else 0) + name_tw
    bot_content_w = avatar_width + (2 if avatar_width else 0) + score_tw
    content_width = max(top_content_w, bot_content_w)

    fps = cfg.getint("display", "fps", fallback=30)
    scroll_in_s = cfg.getfloat("display", "scroll_in_seconds", fallback=0.8)
    hold_s = cfg.getfloat("display", "hold_seconds", fallback=2.0)
    scroll_out_s = cfg.getfloat("display", "scroll_out_seconds", fallback=0.8)

    n_scroll_in = max(1, int(scroll_in_s * fps))
    n_hold = max(1, int(hold_s * fps))
    n_scroll_out = max(1, int(scroll_out_s * fps))

    # Center X for the whole content block
    center_x = (DMD_WIDTH - content_width) // 2
    start_x = DMD_WIDTH  # off-screen right
    end_x = -content_width  # off-screen left

    # Vertical raster bar: build a color lookup by scanline, cycling silver dark → bright → dark
    # Short period = visible bars within the 16px name area
    raster_height = 8  # one full cycle every 8 scanlines = ~2 bars visible in 16px
    raster_colors = []
    for y in range(raster_height):
        t = (y / raster_height) * 2 * math.pi
        s = (math.sin(t) + 1) / 2  # 0→1→0
        r = int(DMD_COLOR_LEFT[0] + (DMD_COLOR_RIGHT[0] - DMD_COLOR_LEFT[0]) * s)
        g = int(DMD_COLOR_LEFT[1] + (DMD_COLOR_RIGHT[1] - DMD_COLOR_LEFT[1]) * s)
        b = int(DMD_COLOR_LEFT[2] + (DMD_COLOR_RIGHT[2] - DMD_COLOR_LEFT[2]) * s)
        raster_colors.append((r, g, b))

    # Amber raster bars for score (sweeps downward)
    SCORE_COLOR_DIM = (180, 90, 0)
    SCORE_COLOR_BRIGHT = (255, 180, 50)
    score_raster_height = 8
    score_raster_colors = []
    for y in range(score_raster_height):
        t = (y / score_raster_height) * 2 * math.pi
        s = (math.sin(t) + 1) / 2
        r = int(SCORE_COLOR_DIM[0] + (SCORE_COLOR_BRIGHT[0] - SCORE_COLOR_DIM[0]) * s)
        g = int(SCORE_COLOR_DIM[1] + (SCORE_COLOR_BRIGHT[1] - SCORE_COLOR_DIM[1]) * s)
        b = int(SCORE_COLOR_DIM[2] + (SCORE_COLOR_BRIGHT[2] - SCORE_COLOR_DIM[2]) * s)
        score_raster_colors.append((r, g, b))

    n_total = n_scroll_in + n_hold + n_scroll_out
    frames = []
    frame_duration_ms = int(1000 / fps)

    SCORE_COLOR = (255, 136, 0)  # Amber for initials effects

    def render_frame(x_offset, frame_idx):
        img = Image.new("RGB", (DMD_WIDTH, DMD_HEIGHT), (0, 0, 0))

        # --- Top line: [logo] machine_name with animated raster bars ---
        top_x = x_offset + (content_width - top_content_w) // 2
        top_y_center = (top_half - name_th) // 2 - name_y_off

        if logo_img:
            logo_y = (top_half - logo_img.size[1]) // 2
            if logo_img.mode == "RGBA":
                tmp = Image.new("RGB", logo_img.size, (0, 0, 0))
                tmp.paste(logo_img, mask=logo_img.split()[3])
                img.paste(tmp, (int(top_x), logo_y))
            else:
                img.paste(logo_img, (int(top_x), logo_y))
            text_x = top_x + logo_width + 2
        else:
            text_x = top_x

        # Render name text white on black, then colorize with raster bars
        name_layer = Image.new("RGB", (DMD_WIDTH, DMD_HEIGHT), (0, 0, 0))
        name_draw = ImageDraw.Draw(name_layer)
        name_draw.text((text_x, top_y_center), name_text, fill=(255, 255, 255), font=name_font)
        name_mask = name_layer.convert("L")

        # Build raster bar gradient: each scanline is one solid color, sweeping vertically
        raster_offset = int((frame_idx / max(1, n_total - 1)) * raster_height * 4)
        grad_img = Image.new("RGB", (DMD_WIDTH, DMD_HEIGHT), (0, 0, 0))
        for py in range(DMD_HEIGHT):
            color = raster_colors[(py + raster_offset) % raster_height]
            for px in range(DMD_WIDTH):
                grad_img.putpixel((px, py), color)

        # Composite: where name_mask is white, use raster colors; elsewhere keep img
        img = Image.composite(grad_img, img, name_mask)

        # --- Bottom line: [avatar] [initials with effect] [score in amber] ---
        bot_x = x_offset + (content_width - bot_content_w) // 2
        bot_y_center = top_half + (bot_half - score_th) // 2 - score_y_off

        if avatar_img:
            av_y = top_half + (bot_half - avatar_img.size[1]) // 2
            if avatar_img.mode == "RGBA":
                tmp = Image.new("RGB", avatar_img.size, (0, 0, 0))
                tmp.paste(avatar_img, mask=avatar_img.split()[3])
                img.paste(tmp, (int(bot_x), av_y))
            else:
                img.paste(avatar_img, (int(bot_x), av_y))
            text_start_x = bot_x + avatar_width + 2
        else:
            text_start_x = bot_x

        # Animate initials with effect
        anim_t = (frame_idx % max(1, n_total)) / max(1, n_total)
        heartbeat_t = (frame_idx / max(1, n_total)) * 6  # 6 beats over the animation
        pulse = (math.sin(heartbeat_t * 2 * math.pi) + 1) / 2  # 0→1→0

        initials_x = int(text_start_x)
        score_num_x = int(text_start_x + initials_tw + space_after_initials)

        if effect_idx == 0:
            # HEARTBEAT PULSE: scale initials with a pumping effect
            scale = 0.8 + 0.4 * pulse  # 0.8x → 1.2x
            big_size = max(6, int(score_font.size * scale))
            try:
                pulse_font = ImageFont.truetype(score_font_path, big_size)
            except (OSError, IOError):
                pulse_font = score_font
            pb = pulse_font.getbbox(initials_text)
            pw, ph = pb[2] - pb[0], pb[3] - pb[1]
            # Center the pulsing initials vertically in bot_half
            py = top_half + (bot_half - ph) // 2 - pb[1]
            draw = ImageDraw.Draw(img)
            draw.text((initials_x, py), initials_text, fill=SCORE_COLOR, font=pulse_font)

        elif effect_idx == 1:
            # COLOR CYCLE: cycle initials through warm colors
            hue_t = (frame_idx / max(1, n_total)) * 3  # 3 full cycles
            phase = (hue_t * 2 * math.pi) % (2 * math.pi)
            cr = int(200 + 55 * math.sin(phase))
            cg = int(120 + 80 * math.sin(phase + 2.1))
            cb = int(50 + 50 * math.sin(phase + 4.2))
            draw = ImageDraw.Draw(img)
            draw.text((initials_x, bot_y_center), initials_text,
                      fill=(cr, cg, cb), font=score_font)

        elif effect_idx == 2:
            # SPARKLE: initials in amber with random bright pixels around them
            import random
            rng = random.Random(frame_idx * 31 + 17)
            draw = ImageDraw.Draw(img)
            draw.text((initials_x, bot_y_center), initials_text,
                      fill=SCORE_COLOR, font=score_font)
            ib = score_font.getbbox(initials_text)
            iw, ih = ib[2] - ib[0], ib[3] - ib[1]
            for _ in range(5):
                sx = initials_x + rng.randint(-2, iw + 2)
                sy = bot_y_center + ib[1] + rng.randint(-2, ih + 2)
                if 0 <= sx < DMD_WIDTH and 0 <= sy < DMD_HEIGHT:
                    bright = rng.randint(200, 255)
                    img.putpixel((sx, sy), (bright, bright, bright))

        elif effect_idx == 3:
            # FLASH FADE: bright white flash that fades to amber, repeating
            flash_phase = (heartbeat_t * 2 * math.pi) % (2 * math.pi)
            fade = max(0, math.sin(flash_phase))  # only positive half = flash then dark
            fr = int(SCORE_COLOR[0] + (255 - SCORE_COLOR[0]) * fade)
            fg = int(SCORE_COLOR[1] + (255 - SCORE_COLOR[1]) * fade)
            fb = int(SCORE_COLOR[2] + (255 - SCORE_COLOR[2]) * fade)
            draw = ImageDraw.Draw(img)
            draw.text((initials_x, bot_y_center), initials_text,
                      fill=(fr, fg, fb), font=score_font)

        # Draw score number with downward-sweeping raster bars (amber shades)
        score_layer = Image.new("RGB", (DMD_WIDTH, DMD_HEIGHT), (0, 0, 0))
        score_draw = ImageDraw.Draw(score_layer)
        score_draw.text((score_num_x, bot_y_center), score_num_text, fill=(255, 255, 255), font=score_font)
        score_mask = score_layer.convert("L")

        # Sweep downward = subtract offset instead of add
        score_raster_offset = int((frame_idx / max(1, n_total - 1)) * score_raster_height * 4)
        score_grad = Image.new("RGB", (DMD_WIDTH, DMD_HEIGHT), (0, 0, 0))
        for py in range(DMD_HEIGHT):
            color = score_raster_colors[(py - score_raster_offset) % score_raster_height]
            for px in range(DMD_WIDTH):
                score_grad.putpixel((px, py), color)

        img = Image.composite(score_grad, img, score_mask)

        return img

    # Scroll in: right -> center
    for i in range(n_scroll_in):
        t = (i + 1) / n_scroll_in
        eased = sine_ease_out(t)
        x = int(start_x + (center_x - start_x) * eased)
        frames.append(render_frame(x, i))

    # Hold at center
    for j in range(n_hold):
        frames.append(render_frame(center_x, n_scroll_in + j))

    # Scroll out: center -> left
    for i in range(n_scroll_out):
        t = (i + 1) / n_scroll_out
        eased = sine_ease_in(t)
        x = int(center_x + (end_x - center_x) * eased)
        frames.append(render_frame(x, n_scroll_in + n_hold + i))

    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=frame_duration_ms,
        loop=0,
    )


def main():
    parser = argparse.ArgumentParser(description="Stern DMD Highscores Display")
    parser.add_argument("--config", required=True, help="Path to stern_dmd.ini")
    parser.add_argument("--output", required=True, help="Output GIF path")
    args = parser.parse_args()

    cfg = load_config(args.config)

    token, cookies = login(cfg)
    if not token:
        print("Login failed")
        return 1
    print("Authenticated with Stern Insider")

    champions = get_cached_champions(token, cookies, cfg)
    if not champions:
        print("No highscores found")
        return 1

    idx = get_next_index(len(champions))
    champion = champions[idx]
    print(f"Displaying: {champion['name']} / {champion['initials']} / {format_score(champion['score'])}")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    generate_gif(champion, cfg, args.output)
    print(f"GIF saved to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

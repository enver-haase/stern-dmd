# Stern DMD Highscores Display

Generates animated 128x32 GIFs showing Grand Champion highscores from Stern Insider Connected pinball machines, designed for the [RPI2DMD](https://github.com/frumpy4/RPI2DMD) Raspberry Pi LED dot matrix display.

Each invocation shows one machine in round-robin order: machine logo + name on top, player avatar + initials + score on the bottom. The display scrolls in from the right, holds, then scrolls out to the left with sine easing.

## Visual effects

- **Machine name**: silver raster bar sweep (upward)
- **Score**: amber raster bar sweep (downward)
- **Player initials**: one of four randomly assigned effects per invocation:
  - Heartbeat pulse (size oscillation)
  - Color cycle (warm color shifts)
  - Sparkle (random bright pixels)
  - Flash fade (white flash fading to amber)
- **Player avatar**: sourced from Stern Insider profile; falls back to a silver pinball icon
- **Machine logo**: square logo from Stern, shrunk to 16x16

## Usage

```bash
python3 stern_dmd_highscores.py --config stern_dmd.ini --output /tmp/stern_highscore_current.gif
```

Run it multiple times to cycle through machines. API results are cached to avoid hammering the Stern servers (default: 3000 seconds between fetches).

## Configuration

### `stern_dmd.ini`

```ini
[stern]
# Path to the credentials file (kept separate so it can be gitignored)
credentials_file = credentials.ini

[display]
# Minimum seconds between API re-fetches (cached results used otherwise)
min_poll_seconds = 3000

# Default/fallback font
font_path = PIXEL_Retro Gaming.ttf

# Font for the machine name (top line)
name_font_path = DEFAULT_GOUDYSTO.TTF

# Font for initials + score (bottom line)
score_font_path = PIXEL_Retro Gaming.ttf

# Animation timing
scroll_in_seconds = 0.8
hold_seconds = 2.0
scroll_out_seconds = 0.8
fps = 30

[api]
login_url = https://insider.sternpinball.com/login
machines_url = https://cms.prd.sternpinball.io/api/v1/portal/user_registered_machines/?group_type=home
highscores_url = https://cms.prd.sternpinball.io/api/v1/portal/game_machine_high_scores/?machine_id={}
location_country = DE
location_continent = EU
```

### `credentials.ini` (not checked into git)

```ini
[stern]
username = your_email@example.com
password = your_password
```

This file holds your Stern Insider Connected login. Create it manually next to `stern_dmd.ini`.

## Dependencies

- Python 3.7+
- Pillow (`pip install Pillow`)
- Bundled fonts: `PIXEL_Retro Gaming.ttf`, `DEFAULT_GOUDYSTO.TTF` (and others for experimentation)
- `pinball_default.png` — fallback avatar for players without a Stern profile picture

## Deployment on the Pi

1. Copy `stern-dmd/` to `/opt/stern-dmd/` on the Pi
2. Create `/opt/stern-dmd/credentials.ini` with your Stern login
3. Add `Highscore_Active=1` to `/media/usb/Config/config.txt`
4. Add the highscore block to `/opt/RPI2DMD/go.sh` (see below)

### go.sh integration

Add after the weather display block:

```bash
# Highscores display
if [ "$Highscore_Active" == "1" ]; then
    python3 /opt/stern-dmd/stern_dmd_highscores.py --config /opt/stern-dmd/stern_dmd.ini --output /tmp/stern_highscore_current.gif
    if [ -f "/tmp/stern_highscore_current.gif" ]; then
        sudo ./RPI2DMD_Anim_clock --led-cols="$Panel_XSize" --led-rows="$Panel_YSize" \
            --led-chain="$Panel_XNumber" --led-parallel="$Panel_YNumber" \
            --led-slowdown-gpio="$GPIO_Slowdown" --led-brightness="${Panel_Brightness[$heure]}" \
            --led-rgb-sequence="$RGB_Order" --led-pwm-bits="$PWM_Bits" \
            -g "/tmp/stern_highscore_current.gif" \
            -T "" -t "0" -D "" -d "0"
    fi
fi
```

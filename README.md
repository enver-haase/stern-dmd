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

## Prerequisites

You need:
- A **Raspberry Pi** running [RPI2DMD](https://github.com/frumpy4/RPI2DMD) with a 128x32 LED matrix panel
- A **Stern Insider Connected** account with at least one registered home machine
- SSH access to the Pi (default login: `pi` / `raspberry`)

## Dependencies

Everything needed is already installed on a standard RPI2DMD Raspbian image:

- **Python 3.7+** — pre-installed on Raspbian Buster
- **Pillow** (Python Imaging Library) — pre-installed on Raspbian Buster (`python3-pil` package)
- **No pip packages required** — the script uses only stdlib + Pillow

If for some reason Pillow is missing, install it:
```bash
sudo apt-get update
sudo apt-get install python3-pil
```

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

## Deployment on the Pi

### Step 1: Copy files to the Pi

From your development machine:
```bash
ssh pi@RPI2DMD  # password: raspberry
sudo mkdir -p /opt/stern-dmd
sudo chown pi:pi /opt/stern-dmd
exit
scp stern_dmd_highscores.py stern_dmd.ini pinball_default.png \
    "PIXEL_Retro Gaming.ttf" DEFAULT_GOUDYSTO.TTF \
    pi@RPI2DMD:/opt/stern-dmd/
```

### Step 2: Create credentials file

```bash
ssh pi@RPI2DMD
cat > /opt/stern-dmd/credentials.ini << 'EOF'
[stern]
username = your_email@example.com
password = your_password
EOF
```

### Step 3: Test it

```bash
python3 /opt/stern-dmd/stern_dmd_highscores.py \
    --config /opt/stern-dmd/stern_dmd.ini \
    --output /tmp/stern_highscore_current.gif
```

You should see output like:
```
Authenticated with Stern Insider
Displaying: GODZILLA / ROC / 1,185,161,670
GIF saved to /tmp/stern_highscore_current.gif
```

### Step 4: Integrate into RPI2DMD display cycle

#### 4a. Add parameter to config.txt

Append to `/media/usb/Config/config.txt`:
```
# Highscore Configuration
Highscore_Active=1
```

#### 4b. Add `Highscore_Active` to the parameter loading function

In `/opt/RPI2DMD/go.sh`, find the `fonction_charge_param` function. Inside it, locate the line:
```bash
Gif_Active Clock_Active Date_Active Weather_Active \
```
and change it to:
```bash
Gif_Active Clock_Active Date_Active Weather_Active Highscore_Active \
```

#### 4c. Add the default variable

Near the other default variable declarations (around `Weather_Active="1"`), add:
```bash
Highscore_Active="1"
```

#### 4d. Add the highscore display block

In the main `while true` / `for file` loop, find the weather display block that ends with:
```bash
		fi
		Current_Clock_Font=...
```

Insert the following **between** the weather `fi` and the `Current_Clock_Font` line:

```bash
		# Highscores display: show previous GIF, render next in background
		if [ "$Highscore_Active" == "1" ]; then
			# Show the previously rendered GIF (skip on first boot)
			if [ -f "/tmp/stern_highscore_current.gif" ]; then
				sudo ./RPI2DMD_Anim_clock --led-cols="$Panel_XSize" --led-rows="$Panel_YSize" \
					--led-chain="$Panel_XNumber" --led-parallel="$Panel_YNumber" \
					--led-slowdown-gpio="$GPIO_Slowdown" --led-brightness="${Panel_Brightness[$heure]}" \
					--led-rgb-sequence="$RGB_Order" --led-pwm-bits="$PWM_Bits" \
					-g "/tmp/stern_highscore_current.gif" \
					-T "" -t "0" -D "" -d "0"
			fi
			# Render next machine in background (if not already rendering)
			if [ ! -f "/tmp/stern_highscore_rendering" ]; then
				(touch /tmp/stern_highscore_rendering && \
				 python3 /opt/stern-dmd/stern_dmd_highscores.py --config /opt/stern-dmd/stern_dmd.ini --output /tmp/stern_highscore_next.gif 2>/dev/null && \
				 mv /tmp/stern_highscore_next.gif /tmp/stern_highscore_current.gif; \
				 rm -f /tmp/stern_highscore_rendering) &
			fi
		fi
```

The display shows the previously rendered GIF instantly (no delay), while the next machine's GIF renders in the background. On first boot after enabling, no highscore is shown until the background render completes (takes ~6 seconds on a Pi); from the second loop iteration onward it displays seamlessly.

### Step 5: Reboot

```bash
sudo reboot
```

The highscore display will now appear in the DMD rotation cycle, showing one machine per loop iteration in round-robin order.

## Disabling

Set `Highscore_Active=0` in `/media/usb/Config/config.txt` (or via the RPI2DMD web interface if it supports custom parameters).

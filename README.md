# Stern DMD Highscores Display

Generates animated GIF highscore displays for Stern pinball machines on a 128x32 LED dot matrix display driven by RPI2DMD.

## Usage

```bash
python3 stern_dmd_highscores.py --config stern_dmd.ini --output /tmp/stern_highscore_current.gif
```

Each invocation displays the next machine's Grand Champion score in round-robin order. API results are cached according to `min_poll_seconds` (default: 3000s).

## Dependencies

- Python 3.7+
- Pillow (`pip install Pillow`)
- Font: `PIXEL_Retro Gaming.ttf` (path configured in `stern_dmd.ini`)

## Deployment (Pi)

1. Copy `stern-dmd/` to `/opt/stern-dmd/` on the Pi
2. Add `Highscore_Active=1` to `/media/usb/Config/config.txt`
3. Add the highscore block to `/opt/RPI2DMD/go.sh` (see below)

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

# Flashing the ASM2464 from the comma (no workstation, no FTDI)

Validated 2026-07-22 on the bench mici (192.168.61.224) + ASM2464PD running the
handmade firmware (`add1:0001 custom v0.1`). Two full flashes, both `VERIFY OK`
on the first verify pass.

## Why the normal flashers fail on the comma

`flash.py` / the `make flash` path push the image over the BOT bulk pipe
(EP 0x02). On the comma's xHCI this fails on every attempt — the very first
bulk OUT dies with `No such device`, `Operation timed out`, or `Pipe error` —
regardless of:

- fresh firmware boot vs long-running
- normal fw (`add1:0001`) vs bootrom (`174c:2463`, via FTDI bootloader strap)
- suppressing tinygrad's claim-time `libusb_reset_device`
- unbinding `usb-storage`/`uas` first
- raising the bulk timeout to 30s

Control transfers (EP0) are rock solid on the same link. So the comma flasher
drives the SPI flash controller **purely via 0xE4/0xE5 XDATA control
transfers** — the same register sequence as `handmade/e4_flash.py`, but the
0x7000 write buffer is loaded with 0xE5 pokes instead of a bulk OUT.

## Image layout (what to flash)

The tool flashes a FULL image at SPI offset 0:

| offset | content |
|--------|---------|
| 0x000  | `config1` (128 B, from `flash.py`) — identity/config block A |
| 0x080  | `config2` (128 B, from `flash.py`) — identity/config block B |
| 0x100  | `firmware_wrapped.bin` = `body_len(4 LE) + body + 0xA5 + checksum(1) + crc32(4 LE)` |

Do NOT flash a raw `firmware.bin` at offset 0 — that overwrites the config
blocks and puts the body where the loader expects the header.

Build the image:

```bash
make -C handmade wrapped
python3 - <<'EOF'
import re
src = open('flash.py').read()
grab = lambda n: bytes(int(x,0) for x in re.findall(r'0x[0-9A-Fa-f]+|\d+',
        re.search(n + r'\s*=\s*bytes\(\[(.*?)\]\)', src, re.S).group(1)))
c1, c2 = grab('config1'), grab('config2')
wrap = open('handmade/build/firmware_wrapped.bin','rb').read()
img = bytearray(b'\xff'*0x100); img[0:128] = c1; img[128:256] = c2; img += wrap
open('full_image.bin','wb').write(img)
EOF
```

## Flashing

Copy `scripts/comma_flash.py` (a.k.a. `/data/egpu_flash2.py` on the bench
comma) and the image to the device, then:

```bash
sudo /usr/local/venv/bin/python /data/egpu_flash2.py /data/full_image.bin
```

It prints `VERIFY OK` when the readback matches. Then reset the bridge to boot
the new firmware (FTDI pulse, DC cycle, or `0xE5 0xCC31=0x01` CPU reset poke).

## Reliability details

- Reads (0x03 + 0x7000 readback via 0xE4) are fully consistent — three 4KB
  reads hash identical.
- Writes are ~1.3% flaky: the running firmware's ISR can clobber the 0x7000
  staging buffer between the poke-load and the page program. The tool handles
  this by **converging**: after the write pass it re-reads the whole image and
  rewrites any mismatched 128-byte chunk, repeating (max 12 passes) until the
  full-image verify is clean. In practice it converges by pass 0-1.
- Only the lower 128 B of the 0x7000 buffer are used per page program (the
  upper half is clobbered by firmware code — same limit as `e4_flash.py`).
- A failed/partial flash does NOT brick the running bridge: the old firmware
  keeps running until reset, so you can always re-flash before resetting. If
  you reset into a bad image, the bootrom (`174c:2463`) is reachable via the
  FTDI bootloader strap and this same tool works against it.

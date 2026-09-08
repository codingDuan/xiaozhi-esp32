import zlib, struct, sys, glob
W, H = 480, 240   # 双眼并排
def png(raw, w, h, out):
    rows = b"".join(b"\x00" + raw[y*w*3:(y+1)*w*3] for y in range(h))
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    data = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9))
            + chunk(b"IEND", b""))
    open(out, "wb").write(data)
for f in sorted(glob.glob("eye_*.rgb")):
    raw = open(f, "rb").read()
    out = f.replace(".rgb", ".png")
    png(raw, W, H, out)
    print(out)

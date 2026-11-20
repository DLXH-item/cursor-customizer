# -*- coding: utf-8 -*-
"""生成软件图标 app.ico"""
import os
from PIL import Image, ImageDraw

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 渐变底色（对角 蓝 -> 紫）
top = (91, 141, 239)
bot = (124, 111, 240)
for y in range(SIZE):
    t = y / (SIZE - 1)
    r = round(top[0] + (bot[0] - top[0]) * t)
    g = round(top[1] + (bot[1] - top[1]) * t)
    b = round(top[2] + (bot[2] - top[2]) * t)
    d.line([(0, y), (SIZE, y)], fill=(r, g, b, 255))

# 箭头光标剪影（白色）
arrow = [
    (78, 46), (78, 186), (108, 154), (132, 196), (154, 184),
    (130, 142), (176, 142),
]
d.polygon(arrow, fill=(255, 255, 255, 245))

# 高光小圆点点缀
d.ellipse((176, 56, 200, 80), fill=(255, 255, 255, 90))

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
img.save(out, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon saved:", out)

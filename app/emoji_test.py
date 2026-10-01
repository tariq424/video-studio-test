from PIL import Image, ImageDraw, ImageFont
import os
f = ImageFont.truetype(r"C:\Windows\Fonts\seguiemj.ttf", 120)
im = Image.new("RGBA", (900, 200), (40, 40, 40, 255)); d = ImageDraw.Draw(im)
d.text((10, 20), "🤖🧠💰🚀🔒", font=f, embedded_color=True)
im.save(r"F:\videos\explainer_studio\emoji_test.png"); print("EMOJI_OK", os.path.exists(r"C:\Windows\Fonts\seguiemj.ttf"))

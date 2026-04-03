import pytesseract
from PIL import Image
import io
import base64

# 测试pytesseract是否安装正确
print("Testing pytesseract...")
try:
    # 测试基本功能
    print(f"pytesseract version: {pytesseract.get_tesseract_version()}")
    print("pytesseract is installed correctly!")
    
    # 测试OCR功能
    # 创建一个简单的测试图片（红色背景，白色文字）
    from PIL import Image, ImageDraw, ImageFont
    
    # 创建图片
    img = Image.new('RGB', (200, 50), color = (255, 0, 0))
    d = ImageDraw.Draw(img)
    # 尝试使用系统字体
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except:
        font = ImageFont.load_default()
    d.text((10,10), "Hello World! 你好世界！", fill=(255,255,255), font=font)
    
    # 保存测试图片
    img.save("test_image.png")
    print("Created test image: test_image.png")
    
    # 测试OCR
    text = pytesseract.image_to_string(img, lang='chi_sim+eng')
    print(f"OCR result: {text}")
    print("OCR test passed!")
    
except Exception as e:
    print(f"Error: {e}")
    print("pytesseract is not working correctly.")

print("Test completed.")

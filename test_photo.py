import os
from main import process_photo
from PIL import Image

# Path to a real photo crop from your output folder
# (after running the bot once, you'll have a file like output/photo_xxxxx.png)
photo_file = "output/raw_9ae15782.png"  # <-- Replace with actual file name

if not os.path.exists(photo_file):
    print(
        f"ERROR: {photo_file} not found. Run the bot first and note the photo filename.")
    exit(1)

# Test classic template (temp1)
print("Testing classic template (temp1)...")
result = process_photo(photo_file, (330, 450), 18, "temp1.jpg", "color")
if result:
    result.save("test_oval.png")
    print("Saved test_oval.png – check if oval mask is visible")
else:
    print("process_photo returned None for temp1")

# Test modern template (temp2)
print("\nTesting modern template (temp2)...")
result2 = process_photo(photo_file, (380, 520), 18, "temp2.jpg", "color")
if result2:
    result2.save("test_rounded.png")
    print("Saved test_rounded.png – check if rounded corners are visible")
else:
    print("process_photo returned None for temp2")

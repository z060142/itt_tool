"""
圖片切割模組
用於將超長圖片切割成多個重疊的切片，以便逐片進行 OCR 識別
"""

from PIL import Image
from typing import List, Tuple, Dict
import os
import tempfile


class ImageSplitter:
    def __init__(self,
                 height_threshold: int = 3600,
                 aspect_ratio_threshold: float = 3.0,
                 slice_height: int = 1400,
                 overlap_ratio: float = 0.18):
        """
        初始化圖片切割器

        Args:
            height_threshold: 高度閾值（px），超過此高度才切割
            aspect_ratio_threshold: 高寬比閾值，超過此比例才切割
            slice_height: 單片高度（px）
            overlap_ratio: 重疊比例（0.0-1.0），推薦 0.15-0.20
        """
        self.height_threshold = height_threshold
        self.aspect_ratio_threshold = aspect_ratio_threshold
        self.slice_height = slice_height
        self.overlap_ratio = overlap_ratio
        self.temp_dir = tempfile.mkdtemp(prefix='img_split_')

    def should_split(self, image_path: str) -> bool:
        """
        判斷圖片是否需要切割

        Args:
            image_path: 圖片路徑

        Returns:
            True 如果需要切割，False 否則
        """
        try:
            with Image.open(image_path) as img:
                width, height = img.size
                aspect_ratio = height / width if width > 0 else 0

                # 檢查條件：高度超過閾值 OR 高寬比超過閾值
                needs_split = (height > self.height_threshold or
                              aspect_ratio > self.aspect_ratio_threshold)

                if needs_split:
                    print(f"圖片尺寸: {width}x{height}, 高寬比: {aspect_ratio:.2f}")
                    print(f"判定為超長圖片，需要切割")

                return needs_split

        except Exception as e:
            print(f"無法讀取圖片 {image_path}: {e}")
            return False

    def split_image(self, image_path: str) -> List[Dict]:
        """
        將圖片切割成多個重疊的切片

        Args:
            image_path: 原始圖片路徑

        Returns:
            切片資訊列表，每個元素包含:
            {
                'path': 切片檔案路徑,
                'index': 切片索引（從0開始）,
                'start_y': 起始 Y 座標,
                'end_y': 結束 Y 座標,
                'overlap_start': 與上一片重疊的起始位置（相對於本片）,
                'overlap_end': 與下一片重疊的結束位置（相對於本片）
            }
        """
        try:
            img = Image.open(image_path)
            width, height = img.size

            # 計算重疊高度
            overlap_height = int(self.slice_height * self.overlap_ratio)

            # 計算實際步進高度（扣除重疊）
            step_height = self.slice_height - overlap_height

            # 計算需要切幾片
            num_slices = (height - overlap_height + step_height - 1) // step_height

            print(f"圖片總高度: {height}px")
            print(f"切片高度: {self.slice_height}px")
            print(f"重疊高度: {overlap_height}px ({self.overlap_ratio*100:.0f}%)")
            print(f"預計切割為 {num_slices} 片")

            slices = []

            for i in range(num_slices):
                # 計算切片的 Y 座標範圍
                start_y = i * step_height
                end_y = min(start_y + self.slice_height, height)

                # 確保最後一片不會太小
                if i == num_slices - 1 and end_y < height:
                    end_y = height

                # 如果這是最後一片且太小，則與上一片合併
                if i > 0 and (end_y - start_y) < self.slice_height * 0.5:
                    print(f"最後一片過小 ({end_y - start_y}px)，與上一片合併")
                    # 更新上一片的範圍
                    slices[-1]['end_y'] = end_y
                    prev_path = slices[-1]['path']

                    # 重新切割上一片
                    prev_start_y = slices[-1]['start_y']
                    cropped = img.crop((0, prev_start_y, width, end_y))
                    cropped.save(prev_path)

                    print(f"合併後切片 {i-1}: Y座標 {prev_start_y}-{end_y} ({end_y - prev_start_y}px)")
                    break

                # 切割圖片
                cropped = img.crop((0, start_y, width, end_y))

                # 儲存切片
                slice_filename = f"slice_{i:03d}.jpg"
                slice_path = os.path.join(self.temp_dir, slice_filename)
                cropped.save(slice_path, 'JPEG', quality=95)

                # 計算重疊區域（相對於本片的座標）
                overlap_start = overlap_height if i > 0 else 0
                overlap_end = end_y - start_y - overlap_height if i < num_slices - 1 else end_y - start_y

                slice_info = {
                    'path': slice_path,
                    'index': i,
                    'start_y': start_y,
                    'end_y': end_y,
                    'height': end_y - start_y,
                    'overlap_start': overlap_start,  # 與上一片重疊的開始位置
                    'overlap_end': overlap_end,      # 與下一片重疊的開始位置
                }

                slices.append(slice_info)

                print(f"切片 {i}: Y座標 {start_y}-{end_y} ({end_y - start_y}px), "
                      f"重疊區域: {overlap_start}-{overlap_end}px")

            img.close()

            return slices

        except Exception as e:
            print(f"圖片切割失敗: {e}")
            return []

    def cleanup(self):
        """
        清理臨時檔案
        """
        try:
            import shutil
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                print(f"已清理臨時目錄: {self.temp_dir}")
        except Exception as e:
            print(f"清理臨時檔案失敗: {e}")

    def get_slice_info(self, slices: List[Dict]) -> str:
        """
        獲取切片資訊摘要

        Args:
            slices: 切片資訊列表

        Returns:
            格式化的摘要字串
        """
        if not slices:
            return "無切片資訊"

        total_height = slices[-1]['end_y']
        overlap_height = int(self.slice_height * self.overlap_ratio)

        info = f"切片總數: {len(slices)}\n"
        info += f"原圖高度: {total_height}px\n"
        info += f"切片高度: {self.slice_height}px\n"
        info += f"重疊高度: {overlap_height}px ({self.overlap_ratio*100:.0f}%)\n"
        info += f"臨時目錄: {self.temp_dir}\n"

        return info


if __name__ == "__main__":
    # 測試程式碼
    print("=== 圖片切割模組測試 ===\n")

    # 建立測試用的超長圖片
    test_img_path = "test_long_image.jpg"
    test_img = Image.new('RGB', (800, 5000), color='white')

    # 繪製一些測試內容（模擬題目）
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(test_img)

    for i in range(20):
        y_pos = i * 250
        draw.rectangle([(50, y_pos + 10), (750, y_pos + 240)], outline='black', width=2)
        draw.text((100, y_pos + 50), f"題目 {i+1}: 這是一個測試題目", fill='black')
        draw.text((100, y_pos + 100), "A. 選項A", fill='black')
        draw.text((100, y_pos + 130), "B. 選項B", fill='black')
        draw.text((100, y_pos + 160), "C. 選項C", fill='black')
        draw.text((100, y_pos + 190), "D. 選項D", fill='black')

    test_img.save(test_img_path)
    print(f"已建立測試圖片: {test_img_path} (800x5000px)\n")

    # 測試切割
    splitter = ImageSplitter(
        height_threshold=3600,
        slice_height=1400,
        overlap_ratio=0.18
    )

    if splitter.should_split(test_img_path):
        slices = splitter.split_image(test_img_path)

        print(f"\n=== 切割結果 ===")
        print(splitter.get_slice_info(slices))

        print(f"\n=== 切片詳細資訊 ===")
        for slice_info in slices:
            print(f"切片 {slice_info['index']}:")
            print(f"  路徑: {slice_info['path']}")
            print(f"  Y座標: {slice_info['start_y']}-{slice_info['end_y']}")
            print(f"  高度: {slice_info['height']}px")
            print(f"  重疊區域: {slice_info['overlap_start']}-{slice_info['overlap_end']}px")
            print()

        # 清理
        splitter.cleanup()

    # 清理測試圖片
    if os.path.exists(test_img_path):
        os.remove(test_img_path)
        print(f"已清理測試圖片: {test_img_path}")

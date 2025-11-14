"""
OpenRouter API客戶端模組
用於調用視覺模型識別圖像中的題目和選項
"""

import requests
import json
import base64
from pathlib import Path
from typing import Dict, Optional, List
from PIL import Image
import io


class OpenRouterClient:
    def __init__(self, api_key: str, model: str, site_url: str = "", site_name: str = ""):
        """
        初始化OpenRouter客戶端

        Args:
            api_key: OpenRouter API密鑰
            model: 使用的模型名稱
            site_url: 網站URL（可選）
            site_name: 網站名稱（可選）
        """
        self.api_key = api_key
        self.model = model
        self.site_url = site_url
        self.site_name = site_name
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    def encode_image_to_base64(self, image_path: str, max_short_side: int = 1200) -> str:
        """
        將本地圖片編碼為base64（自動縮放以節省上傳流量）

        Args:
            image_path: 圖片路徑
            max_short_side: 短邊最大像素（預設 1200）

        Returns:
            base64編碼的圖片字串
        """
        try:
            # 開啟圖片
            img = Image.open(image_path)

            # 轉換為 RGB（處理 PNG 透明背景等）
            if img.mode in ('RGBA', 'LA', 'P'):
                # 建立白色背景
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # 獲取原始尺寸
            width, height = img.size
            short_side = min(width, height)

            # 如果短邊超過限制，等比縮小
            if short_side > max_short_side:
                # 計算縮放比例
                scale = max_short_side / short_side

                # 計算新尺寸
                new_width = int(width * scale)
                new_height = int(height * scale)

                # 使用 LANCZOS 演算法縮放（高質量，適合文字）
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                print(f"上傳前縮放圖片: {width}x{height} -> {new_width}x{new_height}")

            # 將圖片編碼為 base64（在記憶體中處理，不儲存檔案）
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=95, optimize=True)
            encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')

            return f"data:image/jpeg;base64,{encoded}"

        except Exception as e:
            print(f"圖片處理失敗，使用原始檔案: {e}")
            # 如果處理失敗，回退到原始方法
            with open(image_path, "rb") as image_file:
                encoded = base64.b64encode(image_file.read()).decode('utf-8')
                # 獲取圖片副檔名
                ext = Path(image_path).suffix.lower()
                mime_type = {
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.png': 'image/png',
                    '.gif': 'image/gif',
                    '.webp': 'image/webp'
                }.get(ext, 'image/jpeg')

                return f"data:{mime_type};base64,{encoded}"

    def extract_questions_from_image(self, image_path: str) -> Optional[Dict]:
        """
        從圖像中提取題目和選項

        Args:
            image_path: 圖片路徑

        Returns:
            包含題目資訊的字典，如果失敗返回None
        """
        # 編碼圖片
        image_data = self.encode_image_to_base64(image_path)

        # 構建提示詞
        prompt = """請識別圖片中的所有題目和選項，忽略其他無關內容。
請按以下JSON格式輸出，確保嚴格遵守格式：

{
    "questions": [
        {
            "question": "題目內容",
            "options": {
                "A": "選項A內容",
                "B": "選項B內容",
                "C": "選項C內容",
                "D": "選項D內容"
            }
        }
    ]
}

要求：
1. 只提取完整的題目（包含題目文字和選項），文字模糊難以判斷時以解剖學領域為推測標準
2. 忽略螢幕上的其他文字、UI元素、說明文字等
3. 如果有多道題目，請全部提取
4. 選項必須包含A、B、C、D四個選項（如果不足4個，請標註為"無"）
5. 只輸出JSON格式，不要添加任何其他文字說明
6. 確保JSON格式正確，可以被Python的json.loads()解析"""

        # 構建請求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.site_name:
            headers["X-Title"] = self.site_name

        data = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data
                            }
                        }
                    ]
                }
            ]
        }

        try:
            response = requests.post(
                url=self.api_url,
                headers=headers,
                data=json.dumps(data),
                timeout=60
            )

            response.raise_for_status()
            result = response.json()

            # 提取回覆內容
            content = result['choices'][0]['message']['content']

            # 嘗試解析JSON
            # 移除可能的markdown程式碼區塊標記
            content = content.strip()
            if content.startswith('```'):
                # 移除開頭的```json或```
                lines = content.split('\n')
                content = '\n'.join(lines[1:-1]) if len(lines) > 2 else content

            # 解析JSON
            parsed_data = json.loads(content)

            return parsed_data

        except requests.exceptions.RequestException as e:
            print(f"API請求失敗: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"JSON解析失敗: {e}")
            print(f"原始內容: {content}")
            return None
        except Exception as e:
            print(f"未知錯誤: {e}")
            return None


    def ocr_image_slice(self, image_path: str) -> Optional[str]:
        """
        對圖片切片進行 OCR 文字識別（不提取題目結構）

        Args:
            image_path: 圖片切片路徑

        Returns:
            識別出的文字內容，如果失敗返回 None
        """
        # 編碼圖片
        image_data = self.encode_image_to_base64(image_path)

        # OCR 專用 prompt
        prompt = """請將圖片中的所有文字完整識別出來，保持原有格式。

要求：
1. 完整識別所有文字內容，不要遺漏
2. 保留題號格式（例如：1.、2.、3. 或 1)、2)、3)）
3. 保留選項標記（例如：A.、B.、C.、D. 或 (A)、(B)）
4. 保留換行和段落結構
5. 如果有圖表或圖片，標註為 [圖片]
6. 不要添加任何額外說明或註釋
7. 只輸出識別的文字內容本身

請直接輸出識別結果："""

        # 構建請求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.site_name:
            headers["X-Title"] = self.site_name

        data = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data
                            }
                        }
                    ]
                }
            ]
        }

        try:
            response = requests.post(
                url=self.api_url,
                headers=headers,
                data=json.dumps(data),
                timeout=60
            )

            response.raise_for_status()
            result = response.json()

            # 提取回覆內容
            content = result['choices'][0]['message']['content']

            # 清理可能的 markdown 標記
            content = content.strip()
            if content.startswith('```'):
                lines = content.split('\n')
                content = '\n'.join(lines[1:-1]) if len(lines) > 2 else content

            return content

        except requests.exceptions.RequestException as e:
            print(f"OCR API請求失敗: {e}")
            return None
        except Exception as e:
            print(f"OCR未知錯誤: {e}")
            return None

    def process_long_image(self, image_path: str,
                          height_threshold: int = 3600,
                          aspect_ratio_threshold: float = 3.0,
                          slice_height: int = 1400,
                          overlap_ratio: float = 0.18,
                          progress_callback=None) -> Optional[List[Dict]]:
        """
        處理超長圖片（切割 → OCR → 拼接 → 提取題目）

        Args:
            image_path: 原始圖片路徑
            height_threshold: 高度閾值（px）
            aspect_ratio_threshold: 高寬比閾值
            slice_height: 單片高度（px）
            overlap_ratio: 重疊比例
            progress_callback: 進度回調函數 callback(step, message, progress)

        Returns:
            提取的題目列表，如果失敗返回 None
        """
        try:
            from image_splitter import ImageSplitter
            from text_processor import TextProcessor

            # 建立圖片切割器
            splitter = ImageSplitter(
                height_threshold=height_threshold,
                aspect_ratio_threshold=aspect_ratio_threshold,
                slice_height=slice_height,
                overlap_ratio=overlap_ratio
            )

            # 檢查是否需要切割
            if progress_callback:
                progress_callback("check", "檢查圖片尺寸...", 0)

            if not splitter.should_split(image_path):
                # 不需要切割，使用原有方法
                if progress_callback:
                    progress_callback("extract", "圖片未超過閾值，使用標準提取流程", 100)

                result = self.extract_questions_from_image(image_path)
                if result and 'questions' in result:
                    return result['questions']
                return None

            # 需要切割
            if progress_callback:
                progress_callback("split", "切割圖片中...", 5)

            slices = splitter.split_image(image_path)

            if not slices:
                print("圖片切割失敗")
                return None

            # 對每個切片進行 OCR
            ocr_results = []
            total_slices = len(slices)

            for i, slice_info in enumerate(slices):
                if progress_callback:
                    progress = 10 + int((i / total_slices) * 60)
                    progress_callback("ocr", f"識別切片 {i+1}/{total_slices}...", progress)

                text = self.ocr_image_slice(slice_info['path'])

                if text:
                    ocr_results.append(text)
                    print(f"切片 {i+1} OCR完成，文字長度: {len(text)} 字元")
                else:
                    print(f"切片 {i+1} OCR失敗")
                    ocr_results.append("")  # 添加空字串保持順序

            # 拼接文字
            if progress_callback:
                progress_callback("merge", "拼接文字中...", 75)

            processor = TextProcessor()
            merged_text = processor.merge_texts(ocr_results, verbose=True)

            print(f"\n拼接後總文字長度: {len(merged_text)} 字元")

            # 提取題目
            if progress_callback:
                progress_callback("extract", "提取題目中...", 85)

            questions = processor.extract_questions_from_text(merged_text, verbose=True)

            # 清理臨時檔案
            if progress_callback:
                progress_callback("cleanup", "清理臨時檔案...", 95)

            splitter.cleanup()

            if progress_callback:
                progress_callback("done", f"完成！共提取 {len(questions)} 個題目", 100)

            return questions

        except ImportError as e:
            print(f"導入模組失敗: {e}")
            print("請確保 image_splitter.py 和 text_processor.py 在同一目錄")
            return None
        except Exception as e:
            print(f"處理超長圖片時發生錯誤: {e}")
            import traceback
            traceback.print_exc()
            return None


def load_config(config_path: str = "config.json") -> Dict:
    """
    載入配置檔案

    Args:
        config_path: 配置檔案路徑

    Returns:
        配置字典
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

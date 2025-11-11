"""
題目資料庫管理模組
提供題目的增刪改查功能
"""

import json
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import os
import hashlib
import shutil
import difflib
from PIL import Image
import re


class QuestionDatabase:
    def __init__(self, db_file: str = "questions_db.json", image_dir: str = "images",
                 similarity_threshold: float = 0.75, question_weight: float = 0.6,
                 options_weight: float = 0.4, punctuation_mode: str = 'disabled'):
        """
        初始化題目資料庫

        Args:
            db_file: 資料庫檔案路徑
            image_dir: 圖片儲存目錄
            similarity_threshold: 相似度閾值（預設 0.75）
            question_weight: 題目權重（預設 0.6）
            options_weight: 選項權重（預設 0.4）
            punctuation_mode: 標點符號處理模式（'disabled', 'to_fullwidth', 'to_halfwidth'）
        """
        self.db_file = db_file
        self.image_dir = image_dir
        self.similarity_threshold = similarity_threshold
        self.question_weight = question_weight
        self.options_weight = options_weight
        self.punctuation_mode = punctuation_mode
        self.questions = []
        self.next_id = 1  # 下一個可用的 ID（從 1 開始）

        # 建立圖片目錄
        if not os.path.exists(self.image_dir):
            os.makedirs(self.image_dir)

        self.load()

    @staticmethod
    def normalize_punctuation(text: str, mode: str = 'to_fullwidth') -> str:
        """
        標點符號標準化處理

        Args:
            text: 要處理的文字
            mode: 轉換模式
                  'to_fullwidth' - 中文環境下將半形標點轉為全形
                  'to_halfwidth' - 將全形標點轉為半形
                  'disabled' - 不處理

        Returns:
            處理後的文字
        """
        if mode == 'disabled':
            return text

        def is_chinese_context(text: str, pos: int) -> bool:
            """
            檢查指定位置是否在中文環境中
            檢測前後各2個字符，判斷是否包含中文字符或中文標點
            """
            # 擴大檢測範圍
            start = max(0, pos - 2)
            end = min(len(text), pos + 3)
            context = text[start:end]

            # 中文字符範圍（包含常用漢字）
            chinese_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
            # 中文標點符號
            chinese_punct = '，。！？；：「」『』（）《》〈〉【】、·…—'

            # 檢查上下文中是否包含中文字符或中文標點
            has_chinese = bool(chinese_pattern.search(context))
            has_chinese_punct = any(p in context for p in chinese_punct)

            return has_chinese or has_chinese_punct

        if mode == 'to_fullwidth':
            # 半形 → 全形（僅在中文環境下）
            result = []
            for i, char in enumerate(text):
                if char == ',' and is_chinese_context(text, i):
                    result.append('，')
                elif char == '?' and is_chinese_context(text, i):
                    result.append('？')
                elif char == '!' and is_chinese_context(text, i):
                    result.append('！')
                elif char == ':' and is_chinese_context(text, i):
                    result.append('：')
                elif char == ';' and is_chinese_context(text, i):
                    result.append('；')
                elif char == '.' and is_chinese_context(text, i):
                    # 句號需要更謹慎，避免數字中的小數點
                    if i > 0 and i < len(text) - 1:
                        prev_char = text[i-1]
                        next_char = text[i+1]
                        # 如果前後都不是數字，才轉換
                        if not (prev_char.isdigit() and next_char.isdigit()):
                            result.append('。')
                        else:
                            result.append(char)
                    else:
                        result.append('。')
                else:
                    result.append(char)
            return ''.join(result)

        elif mode == 'to_halfwidth':
            # 全形 → 半形
            replacements = {
                '，': ',',
                '？': '?',
                '！': '!',
                '：': ':',
                '；': ';',
                '。': '.'
            }
            for full, half in replacements.items():
                text = text.replace(full, half)
            return text

        return text

    @staticmethod
    def calculate_question_hash(question: str) -> str:
        """
        計算題目內容的 hash 值

        Args:
            question: 題目內容

        Returns:
            hash 值
        """
        return hashlib.md5(question.strip().encode('utf-8')).hexdigest()

    @staticmethod
    def calculate_options_hash(options: Dict[str, str]) -> str:
        """
        計算選項的 hash 值（忽略選項順序）

        Args:
            options: 選項字典

        Returns:
            hash 值
        """
        # 取出所有選項值，排序後計算 hash
        option_values = sorted([v.strip() for v in options.values()])
        combined = ''.join(option_values)
        return hashlib.md5(combined.encode('utf-8')).hexdigest()

    @staticmethod
    def calculate_combined_hash(question: str, options: Dict[str, str]) -> str:
        """
        計算題目和選項的組合 hash 值

        Args:
            question: 題目內容
            options: 選項字典

        Returns:
            組合 hash 值
        """
        q_hash = QuestionDatabase.calculate_question_hash(question)
        o_hash = QuestionDatabase.calculate_options_hash(options)
        combined = q_hash + o_hash
        return hashlib.md5(combined.encode('utf-8')).hexdigest()

    def calculate_similarity(self, question1: str, options1: Dict[str, str],
                            question2: str, options2: Dict[str, str]) -> float:
        """
        計算兩道題目的相似度

        Args:
            question1: 第一道題目內容
            options1: 第一道題目的選項
            question2: 第二道題目內容
            options2: 第二道題目的選項

        Returns:
            相似度 (0.0 - 1.0)
        """
        # 計算題目相似度
        question_similarity = difflib.SequenceMatcher(None, question1, question2).ratio()

        # 計算選項相似度（排序後比較）
        options1_sorted = sorted(options1.values())
        options2_sorted = sorted(options2.values())

        # 將所有選項連接成字串比較
        options1_str = ''.join(options1_sorted)
        options2_str = ''.join(options2_sorted)
        options_similarity = difflib.SequenceMatcher(None, options1_str, options2_str).ratio()

        # 使用配置的權重
        return question_similarity * self.question_weight + options_similarity * self.options_weight

    def load(self):
        """從檔案載入題目庫"""
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.questions = data.get('questions', [])
                    # 載入 next_id，如果不存在則計算
                    if 'next_id' in data:
                        self.next_id = data['next_id']
                    else:
                        # 向後兼容：計算現有題目中最大的 ID + 1
                        if self.questions:
                            self.next_id = max(q['id'] for q in self.questions) + 1
                        else:
                            self.next_id = 1  # 空資料庫從 1 開始
            except Exception as e:
                print(f"載入題目庫失敗: {e}")
                self.questions = []
                self.next_id = 1  # 錯誤時從 1 開始
        else:
            self.questions = []
            self.next_id = 1  # 新資料庫從 1 開始

    def save(self):
        """儲存題目庫到檔案"""
        try:
            data = {
                'questions': self.questions,
                'next_id': self.next_id,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"儲存題目庫失敗: {e}")
            return False

    def check_duplicate(self, combined_hash: str) -> Optional[Dict]:
        """
        檢查是否存在重複的題目

        Args:
            combined_hash: 組合 hash 值

        Returns:
            如果存在重複返回該題目，否則返回 None
        """
        for q in self.questions:
            if q.get('combined_hash') == combined_hash:
                return q
        return None

    def find_similar_questions(self, question: str, options: Dict[str, str],
                              similarity_threshold: float = None) -> List[Tuple[Dict, float]]:
        """
        尋找近似的題目

        Args:
            question: 題目內容
            options: 選項字典
            similarity_threshold: 相似度閾值（若為 None 則使用實例配置的閾值）

        Returns:
            近似題目列表，每個元素為 (題目資料, 相似度)
        """
        if similarity_threshold is None:
            similarity_threshold = self.similarity_threshold

        similar_questions = []

        for q in self.questions:
            similarity = self.calculate_similarity(
                question, options,
                q['question'], q['options']
            )

            # 如果相似度超過閾值但不是完全相同（1.0），加入列表
            if similarity >= similarity_threshold and similarity < 0.999:
                similar_questions.append((q, similarity))

        # 按相似度排序（高到低）
        similar_questions.sort(key=lambda x: x[1], reverse=True)

        return similar_questions

    def add_question(self, question: str, options: Dict[str, str], source: str = "",
                     correct_answer: str = "", image_path: str = "", note: str = "",
                     check_similarity: bool = True) -> Tuple[int, str, List[Tuple[Dict, float]]]:
        """
        添加一道題目（含去重和近似檢查）

        Args:
            question: 題目內容
            options: 選項字典 {"A": "內容", "B": "內容", ...}
            source: 來源（圖片路徑等）
            correct_answer: 正確答案（如 "A" 或 "AB" 多選）
            image_path: 圖片儲存路徑
            note: 注釋內容
            check_similarity: 是否檢查近似題目

        Returns:
            (題目ID, 狀態, 近似題目列表)
            - 狀態: "new" (新題目), "duplicate" (完全重複), "similar" (近似，需使用者決定)
            - 近似題目列表: [(題目資料, 相似度), ...]
        """
        # 標點符號標準化處理（在計算 hash 之前）
        if self.punctuation_mode != 'disabled':
            question = self.normalize_punctuation(question, self.punctuation_mode)
            # 處理選項
            options = {k: self.normalize_punctuation(v, self.punctuation_mode)
                      for k, v in options.items()}

        # 計算 hash 值
        question_hash = self.calculate_question_hash(question)
        options_hash = self.calculate_options_hash(options)
        combined_hash = self.calculate_combined_hash(question, options)

        # 檢查完全重複
        existing = self.check_duplicate(combined_hash)
        if existing:
            print(f"發現重複題目 (ID: {existing['id']}): {question[:30]}...")
            return existing['id'], "duplicate", []

        # 檢查近似題目
        if check_similarity:
            similar_questions = self.find_similar_questions(question, options)
            if similar_questions:
                print(f"發現 {len(similar_questions)} 道近似題目，需要使用者決定")
                # 返回臨時 ID -1，狀態為 "similar"，以及近似題目列表
                return -1, "similar", similar_questions

        # 添加新題目
        question_id = self.next_id
        self.next_id += 1  # 遞增 next_id

        question_data = {
            'id': question_id,
            'question': question,
            'question_hash': question_hash,
            'options': options,
            'options_hash': options_hash,
            'combined_hash': combined_hash,
            'correct_answer': correct_answer,
            'source': source,
            'image_path': image_path,
            'note': note,
            'created_at': datetime.now().isoformat()
        }
        self.questions.append(question_data)
        self.save()
        return question_id, "new", []

    def force_add_question(self, question: str, options: Dict[str, str], source: str = "",
                          correct_answer: str = "", image_path: str = "", note: str = "") -> int:
        """
        強制添加題目（不檢查重複和近似）

        Args:
            question: 題目內容
            options: 選項字典
            source: 來源
            correct_answer: 正確答案
            image_path: 圖片路徑
            note: 注釋內容

        Returns:
            題目ID
        """
        question_id, status, _ = self.add_question(
            question, options, source, correct_answer, image_path, note,
            check_similarity=False
        )
        return question_id

    def add_questions_batch(self, questions_data: List[Dict], source: str = "") -> tuple[List[int], int, int]:
        """
        批量添加題目（含去重統計）

        Args:
            questions_data: 題目列表，每個元素包含question和options
            source: 來源（圖片路徑等）

        Returns:
            (添加的題目ID列表, 新增數量, 重複數量)
        """
        ids = []
        new_count = 0
        duplicate_count = 0

        for q_data in questions_data:
            question_id, is_new = self.add_question(
                question=q_data.get('question', ''),
                options=q_data.get('options', {}),
                correct_answer=q_data.get('correct_answer', ''),
                image_path=q_data.get('image_path', ''),
                source=source
            )
            ids.append(question_id)
            if is_new:
                new_count += 1
            else:
                duplicate_count += 1

        return ids, new_count, duplicate_count

    def save_image(self, source_image_path: str, combined_hash: str, max_short_side: int = 1200) -> str:
        """
        儲存圖片到圖片目錄（含自動縮放）

        Args:
            source_image_path: 原始圖片路徑
            combined_hash: 題目的組合 hash 值（用作檔案名）
            max_short_side: 短邊最大像素（預設 1200）

        Returns:
            儲存後的圖片相對路徑
        """
        if not os.path.exists(source_image_path):
            return ""

        # 取得副檔名
        ext = os.path.splitext(source_image_path)[1]
        # 使用 hash 作為檔案名，強制使用 .jpg 以節省空間
        dest_filename = f"{combined_hash}.jpg"
        dest_path = os.path.join(self.image_dir, dest_filename)

        # 如果檔案已存在（重複題目），不需要複製
        if os.path.exists(dest_path):
            return os.path.join(self.image_dir, dest_filename)

        # 處理並儲存圖片
        try:
            # 開啟圖片
            img = Image.open(source_image_path)

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

                print(f"圖片已縮放: {width}x{height} -> {new_width}x{new_height}")

            # 儲存圖片（高質量 JPEG）
            img.save(dest_path, 'JPEG', quality=95, optimize=True)

            return os.path.join(self.image_dir, dest_filename)

        except Exception as e:
            print(f"儲存圖片失敗: {e}")
            # 如果處理失敗，嘗試直接複製
            try:
                shutil.copy2(source_image_path, dest_path)
                return os.path.join(self.image_dir, dest_filename)
            except:
                return ""

    def get_question(self, question_id: int) -> Optional[Dict]:
        """
        獲取指定ID的題目

        Args:
            question_id: 題目ID

        Returns:
            題目資料，如果不存在返回None
        """
        for q in self.questions:
            if q['id'] == question_id:
                return q
        return None

    def get_all_questions(self) -> List[Dict]:
        """
        獲取所有題目

        Returns:
            題目列表
        """
        return self.questions.copy()

    def update_question(self, question_id: int, question: str = None, options: Dict[str, str] = None,
                       correct_answer: str = None, note: str = None) -> bool:
        """
        更新題目

        Args:
            question_id: 題目ID
            question: 新的題目內容（可選）
            options: 新的選項字典（可選）
            correct_answer: 正確答案（可選）
            note: 注釋內容（可選）

        Returns:
            是否更新成功
        """
        for q in self.questions:
            if q['id'] == question_id:
                if question is not None:
                    q['question'] = question
                if options is not None:
                    q['options'] = options
                if correct_answer is not None:
                    q['correct_answer'] = correct_answer
                if note is not None:
                    q['note'] = note
                q['updated_at'] = datetime.now().isoformat()
                self.save()
                return True
        return False

    def delete_question(self, question_id: int) -> bool:
        """
        刪除題目

        Args:
            question_id: 題目ID

        Returns:
            是否刪除成功
        """
        for i, q in enumerate(self.questions):
            if q['id'] == question_id:
                self.questions.pop(i)
                self.save()
                return True
        return False

    def search_questions(self, keyword: str) -> List[Dict]:
        """
        搜尋題目

        Args:
            keyword: 關鍵詞

        Returns:
            匹配的題目列表
        """
        results = []
        keyword_lower = keyword.lower()
        for q in self.questions:
            if keyword_lower in q['question'].lower():
                results.append(q)
            else:
                # 搜尋選項
                for option_value in q['options'].values():
                    if keyword_lower in option_value.lower():
                        results.append(q)
                        break
        return results

    def export_to_text(self, output_file: str, include_answer: bool = True,
                      include_note: bool = True) -> bool:
        """
        匯出題目庫為文字格式

        格式：
        1.(A)題目內容  （有正確答案且 include_answer=True 時）
        1.題目內容     （無正確答案或 include_answer=False 時）
        A.選項A B.選項B C.選項C D.選項D
        注釋: xxxxx    （有注釋且 include_note=True 時）

        Args:
            output_file: 輸出檔案路徑
            include_answer: 是否包含答案（預設 True）
            include_note: 是否包含注釋（預設 True）

        Returns:
            是否匯出成功
        """
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                for i, q in enumerate(self.questions, 1):
                    # 寫入題目（根據選項決定是否包含正確答案）
                    correct_answer = q.get('correct_answer', '')
                    if include_answer and correct_answer:
                        f.write(f"{i}.({correct_answer}){q['question']}\n")
                    else:
                        f.write(f"{i}.{q['question']}\n")

                    # 寫入選項
                    options = q['options']
                    option_line = " ".join([f"{key}.{value}" for key, value in sorted(options.items())])
                    f.write(f"{option_line}\n")

                    # 寫入注釋（如果有且選擇包含）
                    note = q.get('note', '')
                    if include_note and note:
                        f.write(f"注釋: {note}\n")

                    # 題目之間空一行
                    if i < len(self.questions):
                        f.write("\n")

            return True
        except Exception as e:
            print(f"匯出失敗: {e}")
            return False

    def clear_all(self) -> bool:
        """
        清空所有題目

        Returns:
            是否成功
        """
        self.questions = []
        self.next_id = 1  # 重置 next_id（從 1 開始）
        return self.save()

    def get_statistics(self) -> Dict:
        """
        獲取統計資訊

        Returns:
            統計資訊字典
        """
        return {
            'total_questions': len(self.questions),
            'sources': list(set([q.get('source', '') for q in self.questions if q.get('source')])),
            'created_dates': [q.get('created_at', '') for q in self.questions]
        }

    def load_from_file(self, file_path: str) -> bool:
        """
        從指定檔案載入題目庫

        Args:
            file_path: 題庫檔案路徑

        Returns:
            是否載入成功
        """
        if not os.path.exists(file_path):
            print(f"檔案不存在: {file_path}")
            return False

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.questions = data.get('questions', [])
                self.db_file = file_path

                # 載入或計算 next_id
                if 'next_id' in data:
                    self.next_id = data['next_id']
                else:
                    # 向後兼容：計算現有題目中最大的 ID + 1
                    if self.questions:
                        self.next_id = max(q['id'] for q in self.questions) + 1
                    else:
                        self.next_id = 1  # 空資料庫從 1 開始

                return True
        except Exception as e:
            print(f"載入題目庫失敗: {e}")
            return False

    def save_as(self, file_path: str) -> bool:
        """
        將題目庫另存為指定檔案

        Args:
            file_path: 目標檔案路徑

        Returns:
            是否儲存成功
        """
        try:
            data = {
                'questions': self.questions,
                'next_id': self.next_id,
                'last_updated': datetime.now().isoformat()
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.db_file = file_path
            return True
        except Exception as e:
            print(f"另存題目庫失敗: {e}")
            return False

    def import_from_file(self, file_path: str) -> int:
        """
        從另一個題庫檔案匯入題目（合併）

        Args:
            file_path: 要匯入的題庫檔案路徑

        Returns:
            成功匯入的題目數量，失敗返回-1
        """
        if not os.path.exists(file_path):
            print(f"檔案不存在: {file_path}")
            return -1

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                import_questions = data.get('questions', [])

                if not import_questions:
                    return 0

                # 使用 next_id 分配新 ID，避免衝突
                imported_count = 0

                for q in import_questions:
                    # 創建新的題目資料，使用 next_id
                    new_question = {
                        'id': self.next_id,
                        'question': q.get('question', ''),
                        'question_hash': q.get('question_hash', ''),
                        'options': q.get('options', {}),
                        'options_hash': q.get('options_hash', ''),
                        'combined_hash': q.get('combined_hash', ''),
                        'correct_answer': q.get('correct_answer', ''),
                        'source': q.get('source', '') + ' (已匯入)',
                        'image_path': q.get('image_path', ''),
                        'note': q.get('note', ''),
                        'created_at': datetime.now().isoformat()
                    }
                    self.questions.append(new_question)
                    self.next_id += 1  # 遞增 next_id
                    imported_count += 1

                # 儲存合併後的題庫
                self.save()
                return imported_count

        except Exception as e:
            print(f"匯入題目庫失敗: {e}")
            return -1

    def get_current_file(self) -> str:
        """
        獲取當前題庫檔案路徑

        Returns:
            當前題庫檔案路徑
        """
        return self.db_file

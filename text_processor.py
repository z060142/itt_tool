"""
文字處理模組
用於合併 OCR 結果並從文字中提取題目
"""

import re
import difflib
from typing import List, Dict, Tuple, Optional


class TextProcessor:
    def __init__(self,
                 overlap_match_lines: int = 10,
                 min_similarity: float = 0.6):
        """
        初始化文字處理器

        Args:
            overlap_match_lines: 用於匹配重疊區域的行數
            min_similarity: 重疊區域最小相似度閾值
        """
        self.overlap_match_lines = overlap_match_lines
        self.min_similarity = min_similarity

    def merge_texts(self, texts: List[str], verbose: bool = True) -> str:
        """
        合併多個 OCR 文字結果（使用重疊區域去重）

        Args:
            texts: OCR 文字列表，按順序排列
            verbose: 是否顯示詳細資訊

        Returns:
            合併後的完整文字
        """
        if not texts:
            return ""

        if len(texts) == 1:
            return texts[0]

        # 從第一段文字開始
        merged = texts[0]

        for i in range(1, len(texts)):
            prev_text = texts[i - 1]
            curr_text = texts[i]

            if verbose:
                print(f"\n合併文字段落 {i}/{len(texts)-1}...")

            # 找到最佳合併點
            merge_point = self._find_merge_point(prev_text, curr_text, verbose)

            if merge_point is not None:
                # 從合併點開始接續
                merged += curr_text[merge_point:]

                if verbose:
                    print(f"成功合併，合併點位於第 {i} 段的第 {merge_point} 個字元")
            else:
                # 如果找不到合併點，直接拼接（並標記警告）
                merged += "\n[警告：重疊區域匹配失敗，可能有重複或遺漏]\n" + curr_text

                if verbose:
                    print(f"警告：無法找到可靠的合併點，直接拼接")

        return merged

    def _find_merge_point(self, prev_text: str, curr_text: str, verbose: bool = False) -> Optional[int]:
        """
        找到兩段文字的最佳合併點（使用重疊區域比對）

        Args:
            prev_text: 前一段文字
            curr_text: 當前段文字
            verbose: 是否顯示詳細資訊

        Returns:
            合併點在 curr_text 中的位置，如果找不到返回 None
        """
        # 將文字分行
        prev_lines = prev_text.split('\n')
        curr_lines = curr_text.split('\n')

        # 取前一段的末尾 N 行
        prev_tail_lines = prev_lines[-self.overlap_match_lines:]

        # 在當前段的開頭搜尋這些行
        best_match = None
        best_similarity = 0
        best_position = None

        # 搜尋範圍：當前段的前 2*N 行
        search_range = min(self.overlap_match_lines * 2, len(curr_lines))

        for start_idx in range(search_range):
            # 取當前段的 N 行進行比對
            end_idx = min(start_idx + len(prev_tail_lines), len(curr_lines))
            curr_head_lines = curr_lines[start_idx:end_idx]

            # 計算相似度
            similarity = self._calculate_text_similarity(prev_tail_lines, curr_head_lines)

            if similarity > best_similarity:
                best_similarity = similarity
                best_match = start_idx
                # 計算字元位置
                best_position = len('\n'.join(curr_lines[:start_idx + len(prev_tail_lines)]))
                if start_idx + len(prev_tail_lines) < len(curr_lines):
                    best_position += 1  # 加上換行符

        if verbose:
            print(f"  最佳匹配位置: 第 {best_match} 行, 相似度: {best_similarity:.2%}")

        # 如果相似度足夠高，返回合併點
        if best_similarity >= self.min_similarity:
            return best_position
        else:
            return None

    def _calculate_text_similarity(self, lines1: List[str], lines2: List[str]) -> float:
        """
        計算兩組文字行的相似度

        Args:
            lines1: 第一組文字行
            lines2: 第二組文字行

        Returns:
            相似度分數（0.0-1.0）
        """
        if not lines1 or not lines2:
            return 0.0

        # 合併成字串
        text1 = '\n'.join(lines1)
        text2 = '\n'.join(lines2)

        # 使用 SequenceMatcher 計算相似度
        matcher = difflib.SequenceMatcher(None, text1, text2)
        return matcher.ratio()

    def extract_questions_from_text(self, text: str, verbose: bool = True) -> List[Dict]:
        """
        從文字中提取題目

        Args:
            text: 完整文字
            verbose: 是否顯示詳細資訊

        Returns:
            題目列表，每個題目包含:
            {
                'question': 題目內容,
                'options': {'A': '...', 'B': '...', 'C': '...', 'D': '...'},
                'raw_text': 原始文字段落
            }
        """
        if verbose:
            print(f"\n開始從文字中提取題目...")
            print(f"文字總長度: {len(text)} 字元")

        # 分割成行
        lines = text.split('\n')

        # 使用正則表達式找到所有題號
        question_pattern = r'^\s*(\d+)\s*[\.\)、]\s*(.*)$'

        questions = []
        current_question = None
        current_lines = []

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            # 檢查是否是題號
            match = re.match(question_pattern, line)

            if match:
                # 如果已經有當前題目，先處理它
                if current_question is not None:
                    parsed_q = self._parse_question_block('\n'.join(current_lines))
                    if parsed_q:
                        questions.append(parsed_q)

                # 開始新題目
                question_num = match.group(1)
                question_text = match.group(2).strip()

                current_question = {
                    'number': question_num,
                    'start_line': i
                }

                # 如果題號後面直接有內容，加入題目文字
                if question_text:
                    current_lines = [question_text]
                else:
                    current_lines = []

            elif current_question is not None:
                # 屬於當前題目的內容
                current_lines.append(line)

        # 處理最後一個題目
        if current_question is not None and current_lines:
            parsed_q = self._parse_question_block('\n'.join(current_lines))
            if parsed_q:
                questions.append(parsed_q)

        if verbose:
            print(f"共提取到 {len(questions)} 個題目\n")

        return questions

    def _parse_question_block(self, block: str) -> Optional[Dict]:
        """
        解析單個題目區塊

        Args:
            block: 題目區塊文字

        Returns:
            解析後的題目字典，如果解析失敗返回 None
        """
        # 選項模式：A. 、A) 、(A) 、A、等
        option_pattern = r'^\s*([A-D])\s*[\.\)、]?\s*(.+)$'

        lines = block.split('\n')
        question_text = ""
        options = {}
        current_option = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 檢查是否是選項
            match = re.match(option_pattern, line, re.MULTILINE)

            if match:
                option_letter = match.group(1)
                option_text = match.group(2).strip()

                # 儲存當前選項
                options[option_letter] = option_text
                current_option = option_letter
            else:
                # 不是選項，判斷是題目還是選項的續行
                if not options:
                    # 還沒有選項，屬於題目
                    if question_text:
                        question_text += " " + line
                    else:
                        question_text = line
                elif current_option:
                    # 有當前選項，可能是選項的續行
                    options[current_option] += " " + line

        # 驗證題目
        if not question_text or not options:
            return None

        # 補齊選項（如果少於4個，標記為"無"）
        for letter in ['A', 'B', 'C', 'D']:
            if letter not in options:
                options[letter] = "無"

        return {
            'question': question_text.strip(),
            'options': options,
            'raw_text': block
        }

    def validate_question(self, question: Dict) -> Tuple[bool, str]:
        """
        驗證題目格式

        Args:
            question: 題目字典

        Returns:
            (是否有效, 錯誤訊息)
        """
        # 檢查必要欄位
        if 'question' not in question or not question['question']:
            return False, "缺少題目內容"

        if 'options' not in question or not question['options']:
            return False, "缺少選項"

        # 檢查選項數量
        options = question['options']
        if len(options) < 2:
            return False, f"選項數量不足（至少需要2個，目前有{len(options)}個）"

        # 檢查是否有空選項（除了標記為"無"的）
        empty_options = [k for k, v in options.items() if not v or v.strip() == ""]
        if empty_options:
            return False, f"選項 {', '.join(empty_options)} 為空"

        # 檢查題目長度
        if len(question['question']) < 5:
            return False, "題目內容過短（少於5個字元）"

        return True, ""

    def format_question_preview(self, question: Dict, index: int) -> str:
        """
        格式化題目預覽

        Args:
            question: 題目字典
            index: 題目序號

        Returns:
            格式化的預覽文字
        """
        preview = f"\n{'='*60}\n"
        preview += f"題目 {index + 1}\n"
        preview += f"{'='*60}\n"
        preview += f"{question['question']}\n\n"

        for key in sorted(question['options'].keys()):
            preview += f"{key}. {question['options'][key]}\n"

        # 驗證狀態
        is_valid, error_msg = self.validate_question(question)
        if not is_valid:
            preview += f"\n⚠️ 警告: {error_msg}\n"

        return preview


if __name__ == "__main__":
    # 測試程式碼
    print("=== 文字處理模組測試 ===\n")

    # 測試1: 文字合併
    print("測試1: 文字合併（模擬重疊區域）")
    print("-" * 60)

    text1 = """題目1：這是第一個題目
A. 選項A
B. 選項B
C. 選項C
D. 選項D

題目2：這是第二個題目
A. 選項A
B. 選項B"""

    text2 = """題目2：這是第二個題目
A. 選項A
B. 選項B
C. 選項C
D. 選項D

題目3：這是第三個題目
A. 選項A"""

    processor = TextProcessor(overlap_match_lines=5, min_similarity=0.6)

    merged = processor.merge_texts([text1, text2], verbose=True)
    print("\n合併結果:")
    print(merged)

    # 測試2: 題目提取
    print("\n" + "="*60)
    print("測試2: 題目提取")
    print("-" * 60)

    sample_text = """1. 人體最大的器官是什麼？
A. 心臟
B. 肝臟
C. 皮膚
D. 大腦

2. 下列哪個不是消化系統的器官？
A. 胃
B. 小腸
C. 肺
D. 大腸

3. 紅血球的主要功能是？
A. 運送氧氣
B. 抵抗病菌
C. 凝血
D. 產生抗體"""

    questions = processor.extract_questions_from_text(sample_text, verbose=True)

    for i, q in enumerate(questions):
        print(processor.format_question_preview(q, i))

        # 驗證
        is_valid, error = processor.validate_question(q)
        print(f"驗證結果: {'✓ 有效' if is_valid else f'✗ 無效 - {error}'}")

    print(f"\n總計提取 {len(questions)} 個題目")

"""
答題客戶端模組
使用 OpenRouter API 進行答題和注釋生成
"""

import requests
import json
import base64
from typing import Dict, List, Optional, Tuple


class AnswerClient:
    def __init__(self, api_key: str, answer_model: str, note_model: str = None,
                 note_style: str = "", note_max_length: int = 200,
                 site_url: str = "", site_name: str = "", question_type: str = "single"):
        self.api_key = api_key
        self.answer_model = answer_model
        self.note_model = note_model if note_model else answer_model
        self.note_style = note_style
        self.note_max_length = note_max_length
        self.site_url = site_url
        self.site_name = site_name
        self.question_type = question_type  # "single" 或 "multiple"
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    def _encode_image(self, image_path: str) -> Optional[str]:
        """將圖片編碼為 base64"""
        try:
            with open(image_path, 'rb') as f:
                image_data = f.read()
                return base64.b64encode(image_data).decode('utf-8')
        except Exception as e:
            print(f"圖片編碼失敗: {e}")
            return None

    def _get_image_mime_type(self, image_path: str) -> str:
        """根據副檔名獲取 MIME 類型"""
        ext = image_path.lower().split('.')[-1]
        mime_types = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp'
        }
        return mime_types.get(ext, 'image/jpeg')

    def answer_single_question(self, question: str, options: Dict[str, str],
                               image_path: str = "", include_image: bool = False,
                               generate_note: bool = False) -> Tuple[str, str]:
        """
        為單一題目作答

        Args:
            question: 題目內容
            options: 選項字典
            image_path: 圖片路徑
            include_image: 是否包含圖片
            generate_note: 是否生成注釋

        Returns:
            (答案, 注釋) 元組
        """
        # 構建 prompt
        options_text = "\n".join([f"{k}. {v}" for k, v in sorted(options.items())])

        # 根據題目類型調整 prompt
        if self.question_type == "single":
            type_instruction = "這是單選題，請謹慎選擇唯一正確的答案。只能選擇一個選項（如A、B、C或D）。"
            answer_format = "答案選項（單選，只能是A、B、C或D其中之一）"
        else:  # multiple
            type_instruction = "這可能是多選題，請選擇所有正確的答案。可以選擇一個或多個選項（如A、AB、ABC等）。"
            answer_format = "答案選項（如A、AB、ABC等）"

        if generate_note:
            prompt = f"""請回答以下選擇題，並提供注釋說明。

題目：{question}
選項：
{options_text}

{type_instruction}

請以以下JSON格式回答：
{{
    "answer": "{answer_format}",
    "note": "注釋說明"
}}

注釋要求：{self.note_style}
注釋字數限制：{self.note_max_length}字以內"""
        else:
            prompt = f"""請回答以下選擇題。

題目：{question}
選項：
{options_text}

{type_instruction}

請以以下JSON格式回答：
{{
    "answer": "{answer_format}"
}}"""

        # 構建訊息
        messages = []

        if include_image and image_path:
            image_base64 = self._encode_image(image_path)
            if image_base64:
                mime_type = self._get_image_mime_type(image_path)
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                })
            else:
                messages.append({"role": "user", "content": prompt})
        else:
            messages.append({"role": "user", "content": prompt})

        # 發送請求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        if self.site_url or self.site_name:
            headers["HTTP-Referer"] = self.site_url
            headers["X-Title"] = self.site_name

        data = {
            "model": self.answer_model,
            "messages": messages
        }

        try:
            response = requests.post(self.api_url, headers=headers, json=data, timeout=60)
            response.raise_for_status()
            result = response.json()

            content = result['choices'][0]['message']['content']

            # 清理 markdown 標記
            if content.startswith('```json'):
                content = content[7:]
            if content.startswith('```'):
                content = content[3:]
            if content.endswith('```'):
                content = content[:-3]
            content = content.strip()

            # 解析 JSON
            parsed = json.loads(content)
            answer = parsed.get('answer', '')
            note = parsed.get('note', '') if generate_note else ''

            return answer, note

        except Exception as e:
            print(f"答題失敗: {e}")
            return "", ""

    def generate_note_for_question(self, question: str, options: Dict[str, str],
                                   answer: str, image_path: str = "",
                                   include_image: bool = False) -> str:
        """
        為題目生成注釋

        Args:
            question: 題目內容
            options: 選項字典
            answer: 正確答案
            image_path: 圖片路徑
            include_image: 是否包含圖片

        Returns:
            注釋內容
        """
        options_text = "\n".join([f"{k}. {v}" for k, v in sorted(options.items())])

        prompt = f"""請為以下選擇題提供注釋說明。

題目：{question}
選項：
{options_text}
正確答案：{answer}

請以以下JSON格式回答：
{{
    "note": "注釋說明"
}}

注釋要求：{self.note_style}
注釋字數限制：{self.note_max_length}字以內"""

        # 構建訊息
        messages = []

        if include_image and image_path:
            image_base64 = self._encode_image(image_path)
            if image_base64:
                mime_type = self._get_image_mime_type(image_path)
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                })
            else:
                messages.append({"role": "user", "content": prompt})
        else:
            messages.append({"role": "user", "content": prompt})

        # 發送請求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        if self.site_url or self.site_name:
            headers["HTTP-Referer"] = self.site_url
            headers["X-Title"] = self.site_name

        data = {
            "model": self.note_model,
            "messages": messages
        }

        try:
            response = requests.post(self.api_url, headers=headers, json=data, timeout=60)
            response.raise_for_status()
            result = response.json()

            content = result['choices'][0]['message']['content']

            # 清理 markdown 標記
            if content.startswith('```json'):
                content = content[7:]
            if content.startswith('```'):
                content = content[3:]
            if content.endswith('```'):
                content = content[:-3]
            content = content.strip()

            # 解析 JSON
            parsed = json.loads(content)
            note = parsed.get('note', '')

            return note

        except Exception as e:
            print(f"生成注釋失敗: {e}")
            return ""

    def answer_batch(self, questions_data: List[Dict], batch_size: int = 5,
                    skip_answered: bool = False, generate_notes: bool = False,
                    include_image: bool = False) -> List[Dict]:
        """
        批量答題

        Args:
            questions_data: 題目列表，每個包含 question, options, image_path
            batch_size: 一次發送的題目數量
            skip_answered: 是否跳過已有答案的題目
            generate_notes: 是否生成注釋
            include_image: 是否包含圖片

        Returns:
            結果列表，每個包含 id, answer, note
        """
        results = []

        # 處理每一批題目
        for i in range(0, len(questions_data), batch_size):
            batch = questions_data[i:i+batch_size]

            for q_data in batch:
                # 跳過已有答案的題目
                if skip_answered and q_data.get('correct_answer'):
                    results.append({
                        'id': q_data['id'],
                        'answer': q_data['correct_answer'],
                        'note': q_data.get('note', ''),
                        'skipped': True
                    })
                    continue

                # 答題
                answer, note = self.answer_single_question(
                    question=q_data['question'],
                    options=q_data['options'],
                    image_path=q_data.get('image_path', ''),
                    include_image=include_image,
                    generate_note=generate_notes
                )

                results.append({
                    'id': q_data['id'],
                    'answer': answer,
                    'note': note,
                    'skipped': False
                })

        return results

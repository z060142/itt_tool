"""
圖像題目提取系統 - 主程式
提供GUI界面進行批量圖像處理和題目管理
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os
import platform
import subprocess
import queue
import json
from pathlib import Path
from api_client import OpenRouterClient, load_config
from question_database import QuestionDatabase
from answer_client import AnswerClient


class QuestionExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("圖像題目提取系統")
        self.root.geometry("1200x700")

        # 載入配置
        try:
            self.config = load_config()
            self.api_client = OpenRouterClient(
                api_key=self.config['openrouter_api_key'],
                model=self.config['model'],
                site_url=self.config.get('site_url', ''),
                site_name=self.config.get('site_name', '')
            )
        except Exception as e:
            messagebox.showerror("配置錯誤", f"載入配置檔案失敗: {e}\n請確保config.json存在並正確配置")
            self.config = None
            self.api_client = None

        # 初始化資料庫（使用配置的權重參數和標點模式）
        self.db = QuestionDatabase(
            similarity_threshold=self.config.get('similarity_threshold', 0.75),
            question_weight=self.config.get('question_weight', 0.6),
            options_weight=self.config.get('options_weight', 0.4),
            punctuation_mode=self.config.get('punctuation_mode', 'disabled')
        )

        # 初始化答題客戶端
        if self.config:
            answer_model = self.config.get('answer_model', 'anthropic/claude-3.5-sonnet')
            use_same_model = self.config.get('use_same_model_for_note', True)
            note_model = answer_model if use_same_model else self.config.get('note_model', answer_model)

            self.answer_client = AnswerClient(
                api_key=self.config['openrouter_api_key'],
                answer_model=answer_model,
                note_model=note_model,
                note_style=self.config.get('note_style', '簡潔明瞭'),
                note_max_length=self.config.get('note_max_length', 200),
                site_url=self.config.get('site_url', ''),
                site_name=self.config.get('site_name', '')
            )
        else:
            self.answer_client = None

        # 建立待處理清單（用於近似題目比對）
        self.pending_queue = queue.Queue()

        # 一氣呵成模式：併行任務管理
        self.oneshot_task_queue = queue.Queue()  # 待處理的題目佇列
        self.oneshot_active_tasks = 0  # 當前活躍的任務數
        self.oneshot_lock = threading.Lock()  # 執行緒鎖，保護任務計數器
        self.oneshot_total_processed = 0  # 總處理數
        self.oneshot_total_success = 0  # 成功數
        self.oneshot_total_failed = 0  # 失敗數

        # 建立UI
        self.create_ui()

        # 載入題目列表
        self.refresh_question_list()

        # 啟動定期檢查待處理清單
        self.check_pending_queue()

        # 啟動一氣呵成任務處理器
        self.check_oneshot_queue()

    def create_ui(self):
        """建立使用者界面"""
        # 建立主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 配置網格權重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)

        # ===== 左側控制面板 =====
        control_frame = ttk.LabelFrame(main_frame, text="控制面板", padding="10")
        control_frame.grid(row=0, column=0, rowspan=3, sticky=(tk.W, tk.N, tk.S), padx=(0, 10))

        # 檔案操作區
        ttk.Label(control_frame, text="檔案操作", font=('Arial', 9, 'bold')).pack(pady=(0, 5))
        ttk.Button(control_frame, text="開啟題庫", command=self.open_database, width=20).pack(pady=2)
        ttk.Button(control_frame, text="題庫另存為", command=self.save_database_as, width=20).pack(pady=2)
        ttk.Button(control_frame, text="匯入題庫", command=self.import_database, width=20).pack(pady=2)

        # 分隔線
        ttk.Separator(control_frame, orient='horizontal').pack(fill='x', pady=10)

        # 圖片處理區
        ttk.Label(control_frame, text="圖片處理", font=('Arial', 9, 'bold')).pack(pady=(0, 5))
        ttk.Button(control_frame, text="批量上傳圖片", command=self.upload_images, width=20).pack(pady=2)
        ttk.Button(control_frame, text="模型設定", command=self.open_model_settings, width=20).pack(pady=2)
        ttk.Button(control_frame, text="全局設定", command=self.open_global_settings, width=20).pack(pady=2)

        # 分隔線
        ttk.Separator(control_frame, orient='horizontal').pack(fill='x', pady=10)

        # 答題功能區
        ttk.Label(control_frame, text="答題功能", font=('Arial', 9, 'bold')).pack(pady=(0, 5))
        ttk.Button(control_frame, text="批量答題", command=self.batch_answer, width=20).pack(pady=2)
        ttk.Button(control_frame, text="批量注釋", command=self.batch_generate_note, width=20).pack(pady=2)

        # 分隔線
        ttk.Separator(control_frame, orient='horizontal').pack(fill='x', pady=10)

        # 題庫管理區
        ttk.Label(control_frame, text="題庫管理", font=('Arial', 9, 'bold')).pack(pady=(0, 5))
        ttk.Button(control_frame, text="重新整理列表", command=self.refresh_question_list, width=20).pack(pady=2)
        ttk.Button(control_frame, text="匯出題庫", command=self.export_questions, width=20).pack(pady=2)
        ttk.Button(control_frame, text="清空題庫", command=self.clear_database, width=20).pack(pady=2)

        # 分隔線
        ttk.Separator(control_frame, orient='horizontal').pack(fill='x', pady=10)

        # 統計資訊
        self.stats_label = ttk.Label(control_frame, text="題目總數: 0", font=('Arial', 10))
        self.stats_label.pack(pady=5)

        # 當前題庫檔案
        self.file_label = ttk.Label(control_frame, text="", font=('Arial', 8), foreground='gray')
        self.file_label.pack(pady=5)
        self.update_file_label()

        # ===== 頂部搜尋欄 =====
        search_frame = ttk.Frame(main_frame)
        search_frame.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=(0, 10))

        ttk.Label(search_frame, text="搜尋:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_entry = ttk.Entry(search_frame)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(search_frame, text="搜尋", command=self.search_questions).pack(side=tk.LEFT)
        ttk.Button(search_frame, text="清除", command=self.refresh_question_list).pack(side=tk.LEFT, padx=(5, 0))

        # ===== 題目列表 =====
        list_frame = ttk.LabelFrame(main_frame, text="題目列表", padding="10")
        list_frame.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        # 建立Treeview
        columns = ('ID', '題目', '來源')
        self.tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)

        # 定義欄位
        self.tree.heading('ID', text='ID')
        self.tree.heading('題目', text='題目')
        self.tree.heading('來源', text='來源')

        self.tree.column('ID', width=50)
        self.tree.column('題目', width=500)
        self.tree.column('來源', width=200)

        # 添加捲軸
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # 綁定選擇事件
        self.tree.bind('<<TreeviewSelect>>', self.on_question_select)

        # ===== 題目詳情和編輯區域 =====
        detail_frame = ttk.LabelFrame(main_frame, text="題目詳情", padding="10")
        detail_frame.grid(row=2, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))
        detail_frame.columnconfigure(1, weight=1)
        detail_frame.rowconfigure(4, weight=1)

        # 題目ID
        ttk.Label(detail_frame, text="ID:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.id_label = ttk.Label(detail_frame, text="", font=('Arial', 10, 'bold'))
        self.id_label.grid(row=0, column=1, sticky=tk.W, pady=5)

        # 圖片連結
        ttk.Label(detail_frame, text="圖片:").grid(row=0, column=2, sticky=tk.W, pady=5, padx=(20, 0))
        self.image_link = tk.Label(detail_frame, text="", fg="blue", cursor="hand2", font=('Arial', 9, 'underline'))
        self.image_link.grid(row=0, column=3, sticky=tk.W, pady=5)
        self.image_link.bind("<Button-1>", self.open_image)

        # 題目內容
        ttk.Label(detail_frame, text="題目:").grid(row=1, column=0, sticky=(tk.W, tk.N), pady=5)
        self.question_text = scrolledtext.ScrolledText(detail_frame, height=3, width=60)
        self.question_text.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, columnspan=2)

        # 選項
        ttk.Label(detail_frame, text="選項:").grid(row=2, column=0, sticky=(tk.W, tk.N), pady=5)
        options_frame = ttk.Frame(detail_frame)
        options_frame.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5, columnspan=2)

        self.option_entries = {}
        self.option_checkboxes = {}
        for i, option in enumerate(['A', 'B', 'C', 'D']):
            ttk.Label(options_frame, text=f"{option}:").grid(row=i, column=0, sticky=tk.W, pady=2)
            entry = ttk.Entry(options_frame, width=60)
            entry.grid(row=i, column=1, sticky=(tk.W, tk.E), pady=2, padx=(5, 0))

            # 添加複選框用於標記正確答案
            var = tk.BooleanVar()
            checkbox = ttk.Checkbutton(options_frame, text="正確答案", variable=var)
            checkbox.grid(row=i, column=2, sticky=tk.W, pady=2, padx=(10, 0))

            options_frame.columnconfigure(1, weight=1)
            self.option_entries[option] = entry
            self.option_checkboxes[option] = var

        # 注釋
        ttk.Label(detail_frame, text="注釋:").grid(row=3, column=0, sticky=(tk.W, tk.N), pady=5)
        self.note_text = scrolledtext.ScrolledText(detail_frame, height=2, width=60)
        self.note_text.grid(row=3, column=1, sticky=(tk.W, tk.E), pady=5, columnspan=2)

        # 操作按鈕
        button_frame = ttk.Frame(detail_frame)
        button_frame.grid(row=4, column=1, sticky=(tk.W, tk.E), pady=10, columnspan=2)

        ttk.Button(button_frame, text="儲存修改", command=self.save_question).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="刪除題目", command=self.delete_question).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="清除選擇", command=self.clear_selection).pack(side=tk.LEFT, padx=5)

        # 答題按鈕（右側）
        ttk.Button(button_frame, text="答題", command=self.answer_current_question).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="生成注釋", command=self.generate_note_current).pack(side=tk.RIGHT, padx=5)

        # ===== 日誌區域 =====
        log_frame = ttk.LabelFrame(detail_frame, text="處理日誌", padding="5")
        log_frame.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=6, width=80)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 目前選中的題目ID和圖片路徑
        self.current_question_id = None
        self.current_image_path = None

    def log(self, message):
        """添加日誌"""
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def upload_images(self):
        """批量上傳圖片並處理"""
        if not self.api_client:
            messagebox.showerror("錯誤", "請先設置API密鑰")
            return

        # 選擇圖片檔案
        file_paths = filedialog.askopenfilenames(
            title="選擇圖片",
            filetypes=[("圖片檔案", "*.png *.jpg *.jpeg *.gif *.webp"), ("所有檔案", "*.*")]
        )

        if not file_paths:
            return

        # 在新執行緒中處理圖片
        thread = threading.Thread(target=self.process_images, args=(file_paths,))
        thread.start()

    def process_images(self, file_paths):
        """處理圖片（在背景執行緒中運行）"""
        self.log(f"開始處理 {len(file_paths)} 張圖片...")

        # 檢查一氣呵成模式
        oneshot_enabled = self.config.get('one_shot_mode_enabled', False)
        if oneshot_enabled:
            # 重置統計
            with self.oneshot_lock:
                self.oneshot_total_processed = 0
                self.oneshot_total_success = 0
                self.oneshot_total_failed = 0
            self.log("🚀 一氣呵成模式已啟用")

        total_new = 0
        total_duplicate = 0
        total_similar = 0
        oneshot_queued = 0  # 加入一氣呵成佇列的題目數

        for i, file_path in enumerate(file_paths, 1):
            self.log(f"\n正在處理 [{i}/{len(file_paths)}]: {Path(file_path).name}")

            try:
                # 調用API識別
                result = self.api_client.extract_questions_from_image(file_path)

                if result and 'questions' in result:
                    questions = result['questions']
                    self.log(f"識別到 {len(questions)} 道題目")

                    # 處理每道題目
                    for q in questions:
                        # 計算 hash 用於圖片檔名
                        combined_hash = self.db.calculate_combined_hash(
                            q.get('question', ''),
                            q.get('options', {})
                        )
                        # 儲存圖片並獲取路徑
                        image_path = self.db.save_image(file_path, combined_hash)
                        q['image_path'] = image_path

                        # 添加題目（含近似檢測）
                        question_id, status, similar_questions = self.db.add_question(
                            question=q.get('question', ''),
                            options=q.get('options', {}),
                            correct_answer=q.get('correct_answer', ''),
                            image_path=image_path,
                            source=file_path
                        )

                        if status == "new":
                            total_new += 1
                            self.log(f"  新增題目 ID: {question_id}")

                            # 一氣呵成：自動加入任務佇列
                            if oneshot_enabled:
                                task_data = {
                                    'question_id': question_id,
                                    'action': self.config.get('one_shot_action', 'answer'),
                                    'include_image': self.config.get('one_shot_include_image', True)
                                }
                                self.oneshot_task_queue.put(task_data)
                                oneshot_queued += 1

                        elif status == "duplicate":
                            total_duplicate += 1
                            self.log(f"  跳過重複題目 (ID: {question_id})")
                        elif status == "similar":
                            total_similar += 1
                            self.log(f"  發現近似題目，加入待處理清單")
                            # 加入待處理清單
                            pending_data = {
                                'new_question': q,
                                'similar_questions': similar_questions,
                                'source': file_path,
                                'image_path': image_path
                            }
                            self.pending_queue.put(pending_data)

                else:
                    self.log("未識別到題目或格式錯誤")

            except Exception as e:
                self.log(f"處理失敗: {e}")

        self.log(f"\n所有圖片處理完成！")
        self.log(f"總計 - 新增: {total_new} 道, 重複: {total_duplicate} 道, 近似待處理: {total_similar} 道")

        if oneshot_enabled and oneshot_queued > 0:
            action_name = {'answer': '答題', 'note': '解題', 'both': '答題+解題'}
            action_text = action_name.get(self.config.get('one_shot_action', 'answer'), '處理')
            self.log(f"🚀 已加入 {oneshot_queued} 道題目到一氣呵成佇列（{action_text}）")
            self.log(f"   最大併行數: {self.config.get('one_shot_max_concurrent', 3)}")

        # 重新整理列表
        self.root.after(0, self.refresh_question_list)

    def refresh_question_list(self):
        """重新整理題目列表"""
        # 清空列表
        for item in self.tree.get_children():
            self.tree.delete(item)

        # 載入所有題目
        questions = self.db.get_all_questions()

        for q in questions:
            self.tree.insert('', tk.END, values=(
                q['id'],
                q['question'][:80] + '...' if len(q['question']) > 80 else q['question'],
                Path(q.get('source', '')).name if q.get('source') else ''
            ))

        # 更新統計
        self.stats_label.config(text=f"題目總數: {len(questions)}")

    def search_questions(self):
        """搜尋題目"""
        keyword = self.search_entry.get().strip()
        if not keyword:
            self.refresh_question_list()
            return

        # 清空列表
        for item in self.tree.get_children():
            self.tree.delete(item)

        # 搜尋
        results = self.db.search_questions(keyword)

        for q in results:
            self.tree.insert('', tk.END, values=(
                q['id'],
                q['question'][:80] + '...' if len(q['question']) > 80 else q['question'],
                Path(q.get('source', '')).name if q.get('source') else ''
            ))

        self.log(f"搜尋 '{keyword}' 找到 {len(results)} 條結果")

    def on_question_select(self, event):
        """選擇題目時的回調"""
        selection = self.tree.selection()
        if not selection:
            return

        # 獲取選中的項目
        item = selection[0]
        values = self.tree.item(item, 'values')
        question_id = int(values[0])

        # 載入題目詳情
        question = self.db.get_question(question_id)
        if question:
            self.current_question_id = question_id
            self.id_label.config(text=str(question_id))

            # 顯示圖片連結
            image_path = question.get('image_path', '')
            if image_path and os.path.exists(image_path):
                self.current_image_path = image_path
                self.image_link.config(text="點擊查看圖片")
            else:
                self.current_image_path = None
                self.image_link.config(text="無圖片")

            # 顯示題目
            self.question_text.delete('1.0', tk.END)
            self.question_text.insert('1.0', question['question'])

            # 顯示選項
            options = question['options']
            correct_answer = question.get('correct_answer', '')
            for key in ['A', 'B', 'C', 'D']:
                self.option_entries[key].delete(0, tk.END)
                self.option_entries[key].insert(0, options.get(key, ''))

                # 設置複選框狀態
                self.option_checkboxes[key].set(key in correct_answer)

            # 顯示注釋
            self.note_text.delete('1.0', tk.END)
            note = question.get('note', '')
            if note:
                self.note_text.insert('1.0', note)

    def save_question(self):
        """儲存題目修改"""
        if self.current_question_id is None:
            messagebox.showwarning("警告", "請先選擇一道題目")
            return

        # 獲取編輯的內容
        question = self.question_text.get('1.0', tk.END).strip()
        options = {key: entry.get().strip() for key, entry in self.option_entries.items()}

        # 收集正確答案
        correct_answer = ''.join([key for key in ['A', 'B', 'C', 'D'] if self.option_checkboxes[key].get()])

        # 獲取注釋
        note = self.note_text.get('1.0', tk.END).strip()

        # 更新資料庫
        success = self.db.update_question(self.current_question_id, question, options, correct_answer, note)

        if success:
            messagebox.showinfo("成功", "題目已更新")
            self.refresh_question_list()
            self.log(f"更新題目 ID: {self.current_question_id}")
        else:
            messagebox.showerror("錯誤", "更新失敗")

    def delete_question(self):
        """刪除題目"""
        if self.current_question_id is None:
            messagebox.showwarning("警告", "請先選擇一道題目")
            return

        # 確認刪除
        if messagebox.askyesno("確認", f"確定要刪除題目 {self.current_question_id} 嗎？"):
            success = self.db.delete_question(self.current_question_id)
            if success:
                messagebox.showinfo("成功", "題目已刪除")
                self.clear_selection()
                self.refresh_question_list()
                self.log(f"刪除題目 ID: {self.current_question_id}")
            else:
                messagebox.showerror("錯誤", "刪除失敗")

    def clear_selection(self):
        """清除選擇"""
        self.current_question_id = None
        self.current_image_path = None
        self.id_label.config(text="")
        self.image_link.config(text="")
        self.question_text.delete('1.0', tk.END)
        self.note_text.delete('1.0', tk.END)
        for entry in self.option_entries.values():
            entry.delete(0, tk.END)
        for checkbox in self.option_checkboxes.values():
            checkbox.set(False)

    def open_image(self, event=None):
        """開啟圖片"""
        if not self.current_image_path:
            messagebox.showwarning("警告", "沒有可顯示的圖片")
            return

        if not os.path.exists(self.current_image_path):
            messagebox.showerror("錯誤", "圖片檔案不存在")
            return

        # 使用系統預設程式開啟圖片
        try:
            if platform.system() == 'Windows':
                os.startfile(self.current_image_path)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', self.current_image_path])
            else:  # Linux
                subprocess.run(['xdg-open', self.current_image_path])
        except Exception as e:
            messagebox.showerror("錯誤", f"無法開啟圖片: {e}")

    def export_questions(self):
        """匯出題庫"""
        if len(self.db.get_all_questions()) == 0:
            messagebox.showwarning("警告", "題庫為空，無法匯出")
            return

        # 彈出匯出選項對話框
        ExportOptionsDialog(self.root, self.db, self.log)

    def clear_database(self):
        """清空題庫"""
        if messagebox.askyesno("確認", "確定要清空所有題目嗎？此操作不可復原！"):
            if messagebox.askyesno("再次確認", "真的要刪除所有題目嗎？"):
                success = self.db.clear_all()
                if success:
                    messagebox.showinfo("成功", "題庫已清空")
                    self.clear_selection()
                    self.refresh_question_list()
                    self.update_file_label()
                    self.log("清空題庫")
                else:
                    messagebox.showerror("錯誤", "清空失敗")

    def open_database(self):
        """開啟題庫檔案"""
        file_path = filedialog.askopenfilename(
            title="開啟題庫",
            defaultextension=".json",
            filetypes=[("JSON檔案", "*.json"), ("所有檔案", "*.*")]
        )

        if file_path:
            success = self.db.load_from_file(file_path)
            if success:
                messagebox.showinfo("成功", f"已開啟題庫: {Path(file_path).name}")
                self.clear_selection()
                self.refresh_question_list()
                self.update_file_label()
                self.log(f"開啟題庫: {file_path}")
            else:
                messagebox.showerror("錯誤", "開啟題庫失敗")

    def save_database_as(self):
        """題庫另存為"""
        file_path = filedialog.asksaveasfilename(
            title="題庫另存為",
            defaultextension=".json",
            filetypes=[("JSON檔案", "*.json"), ("所有檔案", "*.*")]
        )

        if file_path:
            success = self.db.save_as(file_path)
            if success:
                messagebox.showinfo("成功", f"題庫已另存為: {Path(file_path).name}")
                self.update_file_label()
                self.log(f"題庫另存為: {file_path}")
            else:
                messagebox.showerror("錯誤", "另存題庫失敗")

    def import_database(self):
        """匯入題庫（合併）"""
        file_path = filedialog.askopenfilename(
            title="匯入題庫",
            defaultextension=".json",
            filetypes=[("JSON檔案", "*.json"), ("所有檔案", "*.*")]
        )

        if file_path:
            imported_count = self.db.import_from_file(file_path)
            if imported_count > 0:
                messagebox.showinfo("成功", f"成功匯入 {imported_count} 道題目")
                self.refresh_question_list()
                self.log(f"匯入題庫: {file_path}，共 {imported_count} 道題目")
            elif imported_count == 0:
                messagebox.showwarning("警告", "所選題庫中沒有題目")
            else:
                messagebox.showerror("錯誤", "匯入題庫失敗")

    def update_file_label(self):
        """更新當前檔案標籤"""
        current_file = self.db.get_current_file()
        file_name = Path(current_file).name
        self.file_label.config(text=f"當前檔案: {file_name}")

    @staticmethod
    def contains_image_keywords(text: str) -> bool:
        """
        檢測文字中是否包含圖片相關關鍵字

        Args:
            text: 要檢測的文字

        Returns:
            是否包含圖片關鍵字
        """
        # 圖片相關關鍵字列表（繁體、簡體、英文）
        keywords = [
            # 繁體中文
            '圖', '圖片', '圖像', '圖表', '照片', '截圖',
            # 簡體中文
            '图', '图片', '图像', '图表', '照片', '截图',
            # 英文
            'image', 'images', 'picture', 'pictures', 'photo', 'photos',
            'figure', 'figures', 'screenshot', 'pic', 'pics'
        ]

        # 轉為小寫進行比對（英文不區分大小寫）
        text_lower = text.lower()

        # 檢查是否包含任一關鍵字
        return any(keyword.lower() in text_lower for keyword in keywords)

    def open_model_settings(self):
        """開啟模型設定"""
        ModelSettingsDialog(self.root, self.config, self.reload_clients, self.log)

    def reload_clients(self, new_config):
        """重新載入客戶端"""
        self.config = new_config

        # 重新載入 API 客戶端
        self.api_client = OpenRouterClient(
            api_key=self.config['openrouter_api_key'],
            model=self.config['model'],
            site_url=self.config.get('site_url', ''),
            site_name=self.config.get('site_name', '')
        )

        # 重新載入答題客戶端
        answer_model = self.config.get('answer_model', 'anthropic/claude-3.5-sonnet')
        use_same_model = self.config.get('use_same_model_for_note', True)
        note_model = answer_model if use_same_model else self.config.get('note_model', answer_model)

        self.answer_client = AnswerClient(
            api_key=self.config['openrouter_api_key'],
            answer_model=answer_model,
            note_model=note_model,
            note_style=self.config.get('note_style', '簡潔明瞭'),
            note_max_length=self.config.get('note_max_length', 200),
            site_url=self.config.get('site_url', ''),
            site_name=self.config.get('site_name', '')
        )

    def open_global_settings(self):
        """開啟全局設定對話框"""
        GlobalSettingsDialog(self.root, self.config, self.log)

    def batch_answer(self):
        """批量答題"""
        if not self.answer_client:
            messagebox.showerror("錯誤", "請先設定答題模型")
            return

        if len(self.db.get_all_questions()) == 0:
            messagebox.showwarning("警告", "題庫為空")
            return

        BatchAnswerDialog(self.root, self.db, self.answer_client, self.config,
                         self.refresh_question_list, self.log)

    def batch_generate_note(self):
        """批量生成注釋"""
        if not self.answer_client:
            messagebox.showerror("錯誤", "請先設定答題模型")
            return

        if len(self.db.get_all_questions()) == 0:
            messagebox.showwarning("警告", "題庫為空")
            return

        BatchGenerateNoteDialog(self.root, self.db, self.answer_client, self.config,
                               self.refresh_question_list, self.log)

    def answer_current_question(self):
        """為當前題目答題"""
        if self.current_question_id is None:
            messagebox.showwarning("警告", "請先選擇一道題目")
            return

        if not self.answer_client:
            messagebox.showerror("錯誤", "請先設定答題模型")
            return

        SingleAnswerDialog(self.root, self.db, self.answer_client, self.current_question_id,
                          self.on_question_select_refresh, self.log)

    def generate_note_current(self):
        """為當前題目生成注釋"""
        if self.current_question_id is None:
            messagebox.showwarning("警告", "請先選擇一道題目")
            return

        if not self.answer_client:
            messagebox.showerror("錯誤", "請先設定答題模型")
            return

        question = self.db.get_question(self.current_question_id)
        if not question:
            return

        # 檢查是否有答案
        if not question.get('correct_answer'):
            messagebox.showwarning("警告", "此題目尚未設定答案，無法生成注釋")
            return

        GenerateNoteDialog(self.root, self.db, self.answer_client, self.current_question_id,
                          self.on_question_select_refresh, self.log)

    def on_question_select_refresh(self):
        """重新選擇當前題目（用於更新顯示）"""
        if self.current_question_id is not None:
            question = self.db.get_question(self.current_question_id)
            if question:
                # 更新顯示
                self.question_text.delete('1.0', tk.END)
                self.question_text.insert('1.0', question['question'])

                # 更新選項和答案
                options = question['options']
                correct_answer = question.get('correct_answer', '')
                for key in ['A', 'B', 'C', 'D']:
                    self.option_entries[key].delete(0, tk.END)
                    self.option_entries[key].insert(0, options.get(key, ''))
                    self.option_checkboxes[key].set(key in correct_answer)

                # 更新注釋
                self.note_text.delete('1.0', tk.END)
                note = question.get('note', '')
                if note:
                    self.note_text.insert('1.0', note)

    def check_pending_queue(self):
        """定期檢查待處理清單並彈出比對視窗"""
        try:
            # 非阻塞檢查
            pending_data = self.pending_queue.get_nowait()
            # 彈出比對視窗
            self.show_comparison_dialog(pending_data)
        except queue.Empty:
            pass

        # 每 500ms 檢查一次
        self.root.after(500, self.check_pending_queue)

    def show_comparison_dialog(self, pending_data):
        """
        顯示比對對話框

        Args:
            pending_data: 字典包含 {
                'new_question': 新題目資料,
                'similar_questions': 近似題目列表,
                'source': 來源,
                'image_path': 圖片路徑
            }
        """
        ComparisonDialog(self.root, self.db, pending_data, self.refresh_question_list, self.log)

    def check_oneshot_queue(self):
        """定期檢查一氣呵成任務佇列並啟動處理"""
        # 檢查是否啟用一氣呵成模式
        if not self.config.get('one_shot_mode_enabled', False):
            self.root.after(500, self.check_oneshot_queue)
            return

        max_concurrent = self.config.get('one_shot_max_concurrent', 3)

        # 嘗試啟動新任務（如果有空位）
        with self.oneshot_lock:
            while self.oneshot_active_tasks < max_concurrent:
                try:
                    # 非阻塞獲取任務
                    task_data = self.oneshot_task_queue.get_nowait()
                    # 啟動背景執行緒處理任務
                    self.oneshot_active_tasks += 1
                    thread = threading.Thread(target=self.process_oneshot_task, args=(task_data,), daemon=True)
                    thread.start()
                except queue.Empty:
                    break

        # 每 500ms 檢查一次
        self.root.after(500, self.check_oneshot_queue)

    def process_oneshot_task(self, task_data):
        """
        處理一氣呵成任務（在背景執行緒中運行）

        Args:
            task_data: 字典包含 {
                'question_id': 題目 ID,
                'action': 'answer' / 'note' / 'both',
                'include_image': True/False
            }
        """
        question_id = task_data['question_id']
        action = task_data['action']
        include_image = task_data['include_image']

        try:
            # 獲取題目資料
            question_data = self.db.get_question(question_id)
            if not question_data:
                raise Exception(f"找不到題目 ID: {question_id}")

            # 根據動作執行對應處理
            if action in ['answer', 'both']:
                self.oneshot_generate_answer(question_data, include_image)

            if action in ['note', 'both']:
                self.oneshot_generate_note(question_data, include_image)

            # 成功
            with self.oneshot_lock:
                self.oneshot_total_success += 1
                self.oneshot_total_processed += 1

            # 使用預設參數捕獲變數值
            self.root.after(0, lambda qid=question_id, act=action:
                          self.log(f"✓ 一氣呵成完成 ID {qid} ({act})"))

        except Exception as e:
            # 失敗
            with self.oneshot_lock:
                self.oneshot_total_failed += 1
                self.oneshot_total_processed += 1

            # 使用預設參數捕獲變數值
            error_msg = str(e)
            self.root.after(0, lambda qid=question_id, msg=error_msg:
                          self.log(f"✗ 一氣呵成失敗 ID {qid}: {msg}"))

        finally:
            # 釋放任務槽
            with self.oneshot_lock:
                self.oneshot_active_tasks -= 1

    def oneshot_generate_answer(self, question_data, include_image):
        """生成答案（一氣呵成模式）"""
        # 檢查是否應該跳過
        skip_answered = self.config.get('one_shot_skip_answered', True)
        if skip_answered and question_data.get('correct_answer'):
            return

        # 檢查圖片關鍵字
        auto_detect = self.config.get('auto_detect_image_keywords', False)
        if auto_detect and self.contains_image_keywords(question_data['question']):
            include_image = True

        # 調用 API 生成答案（使用 answer_single_question 方法）
        answer, note = self.answer_client.answer_single_question(
            question=question_data['question'],
            options=question_data['options'],
            image_path=question_data.get('image_path', ''),
            include_image=include_image,
            generate_note=False
        )

        if answer:
            # 更新答案（使用 update_question 方法）
            self.db.update_question(question_data['id'], correct_answer=answer)
            self.root.after(0, self.refresh_question_list)

    def oneshot_generate_note(self, question_data, include_image):
        """生成解析（一氣呵成模式）"""
        # 檢查是否有答案
        if not question_data.get('correct_answer'):
            return  # 沒有答案就跳過

        # 檢查是否已有解析
        if question_data.get('note'):
            return  # 已有解析就跳過

        # 檢查圖片關鍵字
        auto_detect = self.config.get('auto_detect_image_keywords', False)
        if auto_detect and self.contains_image_keywords(question_data['question']):
            include_image = True

        # 調用 API 生成解析（使用 generate_note_for_question 方法）
        note = self.answer_client.generate_note_for_question(
            question=question_data['question'],
            options=question_data['options'],
            answer=question_data['correct_answer'],
            image_path=question_data.get('image_path', ''),
            include_image=include_image
        )

        if note:
            # 更新解析（使用 update_question 方法）
            self.db.update_question(question_data['id'], note=note)
            self.root.after(0, self.refresh_question_list)


class ModelSettingsDialog:
    """模型設定對話框"""

    def __init__(self, parent, config, reload_callback, log_callback):
        self.config = config or {}
        self.reload_callback = reload_callback
        self.log_callback = log_callback

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("模型設定")
        self.dialog.geometry("600x600")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.create_ui()

    def create_ui(self):
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # API 密鑰
        ttk.Label(main_frame, text="OpenRouter API 密鑰:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky=tk.W, pady=5)
        self.api_key_entry = ttk.Entry(main_frame, width=50)
        self.api_key_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.api_key_entry.insert(0, self.config.get('openrouter_api_key', ''))

        # 圖片識別模型
        ttk.Label(main_frame, text="圖片識別模型:", font=('Arial', 10, 'bold')).grid(row=1, column=0, sticky=tk.W, pady=5)
        self.extract_model_entry = ttk.Entry(main_frame, width=50)
        self.extract_model_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.extract_model_entry.insert(0, self.config.get('model', 'qwen/qwen3-vl-235b-a22b-instruct'))

        # 答題模型
        ttk.Label(main_frame, text="答題模型:", font=('Arial', 10, 'bold')).grid(row=2, column=0, sticky=tk.W, pady=5)
        self.answer_model_entry = ttk.Entry(main_frame, width=50)
        self.answer_model_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.answer_model_entry.insert(0, self.config.get('answer_model', 'anthropic/claude-3.5-sonnet'))

        # 注釋模型選項
        self.use_same_model_var = tk.BooleanVar(value=self.config.get('use_same_model_for_note', True))
        ttk.Checkbutton(main_frame, text="注釋使用答題模型", variable=self.use_same_model_var,
                       command=self.toggle_note_model).grid(row=3, column=1, sticky=tk.W, pady=5, padx=5)

        ttk.Label(main_frame, text="注釋模型:", font=('Arial', 10, 'bold')).grid(row=4, column=0, sticky=tk.W, pady=5)
        self.note_model_entry = ttk.Entry(main_frame, width=50)
        self.note_model_entry.grid(row=4, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.note_model_entry.insert(0, self.config.get('note_model', ''))

        # 注釋風格
        ttk.Label(main_frame, text="注釋風格:", font=('Arial', 10, 'bold')).grid(row=5, column=0, sticky=tk.W, pady=5)
        self.note_style_entry = ttk.Entry(main_frame, width=50)
        self.note_style_entry.grid(row=5, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.note_style_entry.insert(0, self.config.get('note_style', '簡潔明瞭，重點說明概念和解題思路'))

        # 注釋字數限制
        ttk.Label(main_frame, text="注釋字數限制:", font=('Arial', 10, 'bold')).grid(row=6, column=0, sticky=tk.W, pady=5)
        self.note_max_length_entry = ttk.Entry(main_frame, width=50)
        self.note_max_length_entry.grid(row=6, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.note_max_length_entry.insert(0, str(self.config.get('note_max_length', 200)))

        # 批量答題數量
        ttk.Label(main_frame, text="批量答題數量:", font=('Arial', 10, 'bold')).grid(row=7, column=0, sticky=tk.W, pady=5)
        self.batch_size_entry = ttk.Entry(main_frame, width=50)
        self.batch_size_entry.grid(row=7, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.batch_size_entry.insert(0, str(self.config.get('batch_size', 5)))

        # 按鈕
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=8, column=0, columnspan=2, pady=20)
        ttk.Button(button_frame, text="儲存", command=self.save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=self.dialog.destroy).pack(side=tk.LEFT, padx=5)

        main_frame.columnconfigure(1, weight=1)
        self.toggle_note_model()

    def toggle_note_model(self):
        if self.use_same_model_var.get():
            self.note_model_entry.config(state='disabled')
        else:
            self.note_model_entry.config(state='normal')

    def save_settings(self):
        try:
            new_config = {
                'openrouter_api_key': self.api_key_entry.get().strip(),
                'model': self.extract_model_entry.get().strip(),
                'answer_model': self.answer_model_entry.get().strip(),
                'use_same_model_for_note': self.use_same_model_var.get(),
                'note_model': self.note_model_entry.get().strip(),
                'note_style': self.note_style_entry.get().strip(),
                'note_max_length': int(self.note_max_length_entry.get().strip()),
                'batch_size': int(self.batch_size_entry.get().strip()),
                'site_url': self.config.get('site_url', 'http://localhost'),
                'site_name': self.config.get('site_name', 'Question Extractor'),
                'similarity_threshold': self.config.get('similarity_threshold', 0.75),
                'question_weight': self.config.get('question_weight', 0.6),
                'options_weight': self.config.get('options_weight', 0.4)
            }

            import json
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(new_config, f, indent=2, ensure_ascii=False)

            self.reload_callback(new_config)
            self.log_callback("模型設定已更新")
            self.dialog.destroy()

        except Exception as e:
            messagebox.showerror("錯誤", f"儲存失敗: {e}")


class BatchAnswerDialog:
    """批量答題對話框"""

    def __init__(self, parent, db, answer_client, config, refresh_callback, log_callback):
        self.db = db
        self.answer_client = answer_client
        self.config = config
        self.refresh_callback = refresh_callback
        self.log_callback = log_callback

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("批量答題")
        self.dialog.geometry("400x350")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.create_ui()

    def create_ui(self):
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="批量答題選項", font=('Arial', 12, 'bold')).pack(pady=10)

        # 選項
        self.skip_answered_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(main_frame, text="跳過已有答案的題目", variable=self.skip_answered_var).pack(anchor=tk.W, pady=5)

        self.generate_notes_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(main_frame, text="同時生成注釋", variable=self.generate_notes_var).pack(anchor=tk.W, pady=5)

        self.include_image_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(main_frame, text="包含圖片", variable=self.include_image_var).pack(anchor=tk.W, pady=5)

        # 批次大小
        batch_frame = ttk.Frame(main_frame)
        batch_frame.pack(fill=tk.X, pady=10)
        ttk.Label(batch_frame, text="每批處理題數:").pack(side=tk.LEFT)
        self.batch_size_var = tk.IntVar(value=self.config.get('batch_size', 5))
        ttk.Spinbox(batch_frame, from_=1, to=20, textvariable=self.batch_size_var, width=10).pack(side=tk.LEFT, padx=5)

        # 按鈕
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=20)
        ttk.Button(button_frame, text="開始答題", command=self.start_answering).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=self.dialog.destroy).pack(side=tk.LEFT, padx=5)

    def start_answering(self):
        self.dialog.destroy()

        skip_answered = self.skip_answered_var.get()
        generate_notes = self.generate_notes_var.get()
        include_image = self.include_image_var.get()
        batch_size = self.batch_size_var.get()

        # 在背景執行緒執行
        import threading
        thread = threading.Thread(target=self.process_batch,
                                 args=(skip_answered, generate_notes, include_image, batch_size))
        thread.start()

    def process_batch(self, skip_answered, generate_notes, include_image, batch_size):
        questions = self.db.get_all_questions()
        self.log_callback(f"開始批量答題，共 {len(questions)} 道題目")

        success_count = 0
        skip_count = 0

        for i, q in enumerate(questions, 1):
            # 跳過已有答案
            if skip_answered and q.get('correct_answer'):
                skip_count += 1
                continue

            self.log_callback(f"[{i}/{len(questions)}] 答題中...")

            try:
                # 檢查是否需要自動偵測圖片關鍵字
                auto_detect = self.config.get('auto_detect_image_keywords', False)
                should_include_image = include_image

                if auto_detect and not should_include_image:
                    # 偵測題目中是否包含圖片關鍵字
                    if QuestionExtractorApp.contains_image_keywords(q['question']):
                        should_include_image = True
                        self.log_callback(f"  偵測到圖片關鍵字，自動包含圖片")

                answer, note = self.answer_client.answer_single_question(
                    question=q['question'],
                    options=q['options'],
                    image_path=q.get('image_path', ''),
                    include_image=should_include_image,
                    generate_note=generate_notes
                )

                if answer:
                    self.db.update_question(q['id'], correct_answer=answer, note=note if note else None)
                    success_count += 1
                    self.log_callback(f"  ID {q['id']}: 答案 {answer}")

            except Exception as e:
                self.log_callback(f"  ID {q['id']}: 失敗 - {e}")

        self.log_callback(f"批量答題完成！成功: {success_count}, 跳過: {skip_count}")
        self.refresh_callback()


class SingleAnswerDialog:
    """單一題目答題對話框"""

    def __init__(self, parent, db, answer_client, question_id, refresh_callback, log_callback):
        self.db = db
        self.answer_client = answer_client
        self.question_id = question_id
        self.refresh_callback = refresh_callback
        self.log_callback = log_callback

        self.question = db.get_question(question_id)

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("答題")
        self.dialog.geometry("400x250")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.create_ui()

    def create_ui(self):
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text=f"題目 ID: {self.question_id}", font=('Arial', 12, 'bold')).pack(pady=10)

        # 選項
        self.generate_note_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(main_frame, text="同時生成注釋", variable=self.generate_note_var).pack(anchor=tk.W, pady=5)

        self.include_image_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(main_frame, text="包含圖片", variable=self.include_image_var).pack(anchor=tk.W, pady=5)

        # 按鈕
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=20)
        ttk.Button(button_frame, text="開始", command=self.start_answering).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=self.dialog.destroy).pack(side=tk.LEFT, padx=5)

    def start_answering(self):
        self.dialog.destroy()

        generate_note = self.generate_note_var.get()
        include_image = self.include_image_var.get()

        self.log_callback(f"為題目 ID {self.question_id} 答題中...")

        import threading
        thread = threading.Thread(target=self.process_answer, args=(generate_note, include_image))
        thread.start()

    def process_answer(self, generate_note, include_image):
        try:
            answer, note = self.answer_client.answer_single_question(
                question=self.question['question'],
                options=self.question['options'],
                image_path=self.question.get('image_path', ''),
                include_image=include_image,
                generate_note=generate_note
            )

            if answer:
                self.db.update_question(self.question_id, correct_answer=answer, note=note if note else None)
                self.log_callback(f"答題完成！答案: {answer}")
                self.refresh_callback()
            else:
                self.log_callback("答題失敗")

        except Exception as e:
            self.log_callback(f"答題失敗: {e}")


class GenerateNoteDialog:
    """生成注釋對話框"""

    def __init__(self, parent, db, answer_client, question_id, refresh_callback, log_callback):
        self.db = db
        self.answer_client = answer_client
        self.question_id = question_id
        self.refresh_callback = refresh_callback
        self.log_callback = log_callback

        self.question = db.get_question(question_id)

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("生成注釋")
        self.dialog.geometry("400x200")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.create_ui()

    def create_ui(self):
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text=f"題目 ID: {self.question_id}", font=('Arial', 12, 'bold')).pack(pady=10)

        # 選項
        self.include_image_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(main_frame, text="包含圖片", variable=self.include_image_var).pack(anchor=tk.W, pady=5)

        # 按鈕
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=20)
        ttk.Button(button_frame, text="開始", command=self.start_generating).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=self.dialog.destroy).pack(side=tk.LEFT, padx=5)

    def start_generating(self):
        self.dialog.destroy()

        include_image = self.include_image_var.get()

        self.log_callback(f"為題目 ID {self.question_id} 生成注釋中...")

        import threading
        thread = threading.Thread(target=self.process_generate, args=(include_image,))
        thread.start()

    def process_generate(self, include_image):
        try:
            note = self.answer_client.generate_note_for_question(
                question=self.question['question'],
                options=self.question['options'],
                answer=self.question['correct_answer'],
                image_path=self.question.get('image_path', ''),
                include_image=include_image
            )

            if note:
                self.db.update_question(self.question_id, note=note)
                self.log_callback(f"注釋生成完成！")
                self.refresh_callback()
            else:
                self.log_callback("注釋生成失敗")

        except Exception as e:
            self.log_callback(f"注釋生成失敗: {e}")


class BatchGenerateNoteDialog:
    """批量生成注釋對話框"""

    def __init__(self, parent, db, answer_client, config, refresh_callback, log_callback):
        self.db = db
        self.answer_client = answer_client
        self.config = config
        self.refresh_callback = refresh_callback
        self.log_callback = log_callback

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("批量生成注釋")
        self.dialog.geometry("400x300")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.create_ui()

    def create_ui(self):
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="批量生成注釋選項", font=('Arial', 12, 'bold')).pack(pady=10)

        # 選項
        self.skip_with_note_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(main_frame, text="跳過已有注釋的題目", variable=self.skip_with_note_var).pack(anchor=tk.W, pady=5)

        self.skip_no_answer_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(main_frame, text="跳過沒有答案的題目", variable=self.skip_no_answer_var).pack(anchor=tk.W, pady=5)

        self.include_image_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(main_frame, text="包含圖片", variable=self.include_image_var).pack(anchor=tk.W, pady=5)

        # 說明文字
        info_label = ttk.Label(main_frame, text="※ 注意：生成注釋需要題目已有正確答案",
                               font=('Arial', 9), foreground='gray')
        info_label.pack(pady=10)

        # 按鈕
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=20)
        ttk.Button(button_frame, text="開始生成", command=self.start_generating).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=self.dialog.destroy).pack(side=tk.LEFT, padx=5)

    def start_generating(self):
        self.dialog.destroy()

        skip_with_note = self.skip_with_note_var.get()
        skip_no_answer = self.skip_no_answer_var.get()
        include_image = self.include_image_var.get()

        # 在背景執行緒執行
        import threading
        thread = threading.Thread(target=self.process_batch,
                                 args=(skip_with_note, skip_no_answer, include_image))
        thread.start()

    def process_batch(self, skip_with_note, skip_no_answer, include_image):
        questions = self.db.get_all_questions()
        self.log_callback(f"開始批量生成注釋，共 {len(questions)} 道題目")

        success_count = 0
        skip_count = 0

        for i, q in enumerate(questions, 1):
            # 跳過沒有答案的題目
            if skip_no_answer and not q.get('correct_answer'):
                skip_count += 1
                continue

            # 跳過已有注釋
            if skip_with_note and q.get('note'):
                skip_count += 1
                continue

            self.log_callback(f"[{i}/{len(questions)}] 生成注釋中...")

            try:
                # 檢查是否需要自動偵測圖片關鍵字
                auto_detect = self.config.get('auto_detect_image_keywords', False)
                should_include_image = include_image

                if auto_detect and not should_include_image:
                    # 偵測題目中是否包含圖片關鍵字
                    if QuestionExtractorApp.contains_image_keywords(q['question']):
                        should_include_image = True
                        self.log_callback(f"  偵測到圖片關鍵字，自動包含圖片")

                note = self.answer_client.generate_note_for_question(
                    question=q['question'],
                    options=q['options'],
                    answer=q.get('correct_answer', ''),
                    image_path=q.get('image_path', ''),
                    include_image=should_include_image
                )

                if note:
                    self.db.update_question(q['id'], note=note)
                    success_count += 1
                    self.log_callback(f"  ID {q['id']}: 注釋已生成")

            except Exception as e:
                self.log_callback(f"  ID {q['id']}: 失敗 - {e}")

        self.log_callback(f"批量生成注釋完成！成功: {success_count}, 跳過: {skip_count}")
        self.refresh_callback()


class GlobalSettingsDialog:
    """全局設定對話框"""

    def __init__(self, parent, config, log_callback):
        self.config = config
        self.log_callback = log_callback

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("全局設定")
        self.dialog.geometry("500x500")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.create_ui()

    def create_ui(self):
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="全局設定", font=('Arial', 12, 'bold')).pack(pady=10)

        # 標點符號處理設定
        punct_frame = ttk.LabelFrame(main_frame, text="標點符號自動整理", padding="10")
        punct_frame.pack(fill=tk.X, pady=5)

        self.punctuation_mode_var = tk.StringVar(
            value=self.config.get('punctuation_mode', 'disabled')
        )

        ttk.Radiobutton(punct_frame, text="停用（保持原樣）",
                       variable=self.punctuation_mode_var,
                       value='disabled').pack(anchor=tk.W, pady=2)

        ttk.Radiobutton(punct_frame, text="轉換為全形（中文環境）",
                       variable=self.punctuation_mode_var,
                       value='to_fullwidth').pack(anchor=tk.W, pady=2)

        ttk.Radiobutton(punct_frame, text="轉換為半形",
                       variable=self.punctuation_mode_var,
                       value='to_halfwidth').pack(anchor=tk.W, pady=2)

        # 說明文字
        info_text = "※ 啟用後，AI 返回的題目標點符號會自動統一\n" \
                   "※ 在中文環境下：, → ，  ? → ？\n" \
                   "※ 此處理會在相似比對前執行，確保格式一致"
        ttk.Label(punct_frame, text=info_text, font=('Arial', 8), foreground='gray').pack(pady=5)

        # 圖片關鍵字自動偵測設定
        image_frame = ttk.LabelFrame(main_frame, text="圖片自動偵測", padding="10")
        image_frame.pack(fill=tk.X, pady=5)

        self.auto_detect_image_var = tk.BooleanVar(
            value=self.config.get('auto_detect_image_keywords', False)
        )

        ttk.Checkbutton(image_frame, text="自動偵測題目中的圖片關鍵字",
                       variable=self.auto_detect_image_var).pack(anchor=tk.W, pady=5)

        # 說明文字
        image_info_text = "※ 啟用後，批量答題/注釋時自動偵測關鍵字\n" \
                         "※ 關鍵字：圖、圖片、圖像、照片、图、图像、\n" \
                         "  image、images、picture、pictures、photo 等\n" \
                         "※ 偵測到時會強制發送圖片給 AI，無論是否勾選包含圖片"
        ttk.Label(image_frame, text=image_info_text, font=('Arial', 8), foreground='gray').pack(pady=5)

        # 一氣呵成實驗功能
        oneshot_frame = ttk.LabelFrame(main_frame, text="🚀 一氣呵成（實驗功能）", padding="10")
        oneshot_frame.pack(fill=tk.X, pady=5)

        self.one_shot_enabled_var = tk.BooleanVar(
            value=self.config.get('one_shot_mode_enabled', False)
        )

        ttk.Checkbutton(oneshot_frame, text="啟用一氣呵成模式",
                       variable=self.one_shot_enabled_var,
                       command=self.toggle_oneshot_options).pack(anchor=tk.W, pady=5)

        # 一氣呵成選項容器
        self.oneshot_options_frame = ttk.Frame(oneshot_frame)
        self.oneshot_options_frame.pack(fill=tk.X, padx=20)

        # 動作選擇
        action_frame = ttk.Frame(self.oneshot_options_frame)
        action_frame.pack(fill=tk.X, pady=2)
        ttk.Label(action_frame, text="辨識後動作：").pack(side=tk.LEFT)

        self.one_shot_action_var = tk.StringVar(
            value=self.config.get('one_shot_action', 'answer')
        )
        ttk.Radiobutton(action_frame, text="僅答題", variable=self.one_shot_action_var,
                       value='answer').pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(action_frame, text="僅解題", variable=self.one_shot_action_var,
                       value='note').pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(action_frame, text="答題+解題", variable=self.one_shot_action_var,
                       value='both').pack(side=tk.LEFT, padx=5)

        # 跳過選項
        self.one_shot_skip_answered_var = tk.BooleanVar(
            value=self.config.get('one_shot_skip_answered', True)
        )
        ttk.Checkbutton(self.oneshot_options_frame, text="跳過已答題目",
                       variable=self.one_shot_skip_answered_var).pack(anchor=tk.W, pady=2)

        # 包含圖片
        self.one_shot_include_image_var = tk.BooleanVar(
            value=self.config.get('one_shot_include_image', True)
        )
        ttk.Checkbutton(self.oneshot_options_frame, text="包含圖片發送給 AI",
                       variable=self.one_shot_include_image_var).pack(anchor=tk.W, pady=2)

        # 併行數量
        concurrent_frame = ttk.Frame(self.oneshot_options_frame)
        concurrent_frame.pack(fill=tk.X, pady=2)
        ttk.Label(concurrent_frame, text="最大併行任務數：").pack(side=tk.LEFT)
        self.one_shot_max_concurrent_var = tk.IntVar(
            value=self.config.get('one_shot_max_concurrent', 3)
        )
        concurrent_spinbox = ttk.Spinbox(concurrent_frame, from_=1, to=10, width=5,
                                        textvariable=self.one_shot_max_concurrent_var)
        concurrent_spinbox.pack(side=tk.LEFT, padx=5)

        # 說明文字
        oneshot_info_text = "※ 啟用後，批量圖片辨識完成後自動答題/解題\n" \
                           "※ 每道題目獨立處理，不影響下一張圖片繼續辨識\n" \
                           "※ 併行任務數控制同時處理的題目數量，避免記憶體溢出\n" \
                           "※ 建議併行數設定為 3-5，視電腦效能調整"
        ttk.Label(oneshot_frame, text=oneshot_info_text, font=('Arial', 8), foreground='gray').pack(pady=5)

        # 初始化選項狀態
        self.toggle_oneshot_options()

        # 按鈕
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=15)
        ttk.Button(button_frame, text="儲存", command=self.save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=self.dialog.destroy).pack(side=tk.LEFT, padx=5)

    def toggle_oneshot_options(self):
        """切換一氣呵成選項的啟用/停用狀態"""
        enabled = self.one_shot_enabled_var.get()
        state = 'normal' if enabled else 'disabled'

        # 遍歷所有子元件並設定狀態
        for child in self.oneshot_options_frame.winfo_children():
            if isinstance(child, ttk.Frame):
                # 處理巢狀的 Frame（如動作選擇和併行數量）
                for subchild in child.winfo_children():
                    if isinstance(subchild, (ttk.Radiobutton, ttk.Checkbutton, ttk.Spinbox)):
                        subchild.configure(state=state)
            elif isinstance(child, (ttk.Radiobutton, ttk.Checkbutton, ttk.Spinbox)):
                child.configure(state=state)

    def save_settings(self):
        """儲存設定到 config.json"""
        try:
            # 更新配置
            self.config['punctuation_mode'] = self.punctuation_mode_var.get()
            self.config['auto_detect_image_keywords'] = self.auto_detect_image_var.get()
            self.config['one_shot_mode_enabled'] = self.one_shot_enabled_var.get()
            self.config['one_shot_action'] = self.one_shot_action_var.get()
            self.config['one_shot_skip_answered'] = self.one_shot_skip_answered_var.get()
            self.config['one_shot_include_image'] = self.one_shot_include_image_var.get()
            self.config['one_shot_max_concurrent'] = self.one_shot_max_concurrent_var.get()

            # 儲存到檔案
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)

            self.log_callback(f"全局設定已儲存：標點模式 = {self.punctuation_mode_var.get()}, "
                            f"自動偵測圖片 = {self.auto_detect_image_var.get()}, "
                            f"一氣呵成 = {self.one_shot_enabled_var.get()}")
            messagebox.showinfo("成功", "設定已儲存！\n\n※ 部分設定需重新啟動程式後生效")
            self.dialog.destroy()

        except Exception as e:
            self.log_callback(f"儲存設定失敗: {e}")
            messagebox.showerror("錯誤", f"儲存設定失敗: {e}")


class ExportOptionsDialog:
    """匯出選項對話框類別"""

    def __init__(self, parent, db, log_callback):
        """
        初始化匯出選項對話框

        Args:
            parent: 父視窗
            db: 資料庫實例
            log_callback: 日誌輸出的回調函數
        """
        self.db = db
        self.log_callback = log_callback

        # 建立對話框視窗
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("匯出題庫選項")
        self.dialog.geometry("400x300")
        self.dialog.transient(parent)
        self.dialog.grab_set()  # 模態對話框

        self.create_ui()

    def create_ui(self):
        """建立對話框UI"""
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 標題
        title_label = ttk.Label(
            main_frame,
            text="請選擇匯出內容：",
            font=('Arial', 12, 'bold')
        )
        title_label.pack(pady=(0, 20))

        # 選項區域
        options_frame = ttk.Frame(main_frame)
        options_frame.pack(pady=10)

        # 是否包含答案
        self.include_answer_var = tk.BooleanVar(value=True)
        answer_checkbox = ttk.Checkbutton(
            options_frame,
            text="包含正確答案",
            variable=self.include_answer_var
        )
        answer_checkbox.pack(anchor=tk.W, pady=5)

        # 是否包含注釋
        self.include_note_var = tk.BooleanVar(value=True)
        note_checkbox = ttk.Checkbutton(
            options_frame,
            text="包含注釋",
            variable=self.include_note_var
        )
        note_checkbox.pack(anchor=tk.W, pady=5)

        # 說明文字
        info_label = ttk.Label(
            main_frame,
            text="提示：可取消勾選以隱藏相關內容",
            font=('Arial', 9),
            foreground='gray'
        )
        info_label.pack(pady=10)

        # 按鈕區
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=20)

        ttk.Button(button_frame, text="確認匯出", command=self.confirm_export).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=self.dialog.destroy).pack(side=tk.LEFT, padx=5)

    def confirm_export(self):
        """確認匯出"""
        # 獲取選項
        include_answer = self.include_answer_var.get()
        include_note = self.include_note_var.get()

        # 選擇儲存路徑
        file_path = filedialog.asksaveasfilename(
            title="匯出題庫",
            defaultextension=".txt",
            filetypes=[("文字檔案", "*.txt"), ("所有檔案", "*.*")]
        )

        if file_path:
            # 執行匯出
            success = self.db.export_to_text(file_path, include_answer, include_note)

            if success:
                # 建立匯出摘要
                options_summary = []
                if include_answer:
                    options_summary.append("包含答案")
                else:
                    options_summary.append("不含答案")

                if include_note:
                    options_summary.append("包含注釋")
                else:
                    options_summary.append("不含注釋")

                summary_text = "、".join(options_summary)

                messagebox.showinfo("成功", f"題庫已匯出到: {file_path}\n選項: {summary_text}")
                self.log_callback(f"匯出題庫: {file_path} ({summary_text})")
                self.dialog.destroy()
            else:
                messagebox.showerror("錯誤", "匯出失敗")


class ComparisonDialog:
    """比對對話框類別"""

    def __init__(self, parent, db, pending_data, refresh_callback, log_callback):
        """
        初始化比對對話框

        Args:
            parent: 父視窗
            db: 資料庫實例
            pending_data: 待處理資料
            refresh_callback: 刷新列表的回調函數
            log_callback: 日誌輸出的回調函數
        """
        self.db = db
        self.pending_data = pending_data
        self.refresh_callback = refresh_callback
        self.log_callback = log_callback

        # 建立對話框視窗
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("發現近似題目 - 請選擇")
        self.dialog.geometry("900x600")
        self.dialog.grab_set()  # 模態對話框

        # 提取資料
        self.new_question = pending_data['new_question']
        self.similar_questions = pending_data['similar_questions']
        self.source = pending_data['source']
        self.image_path = pending_data['image_path']

        self.create_ui()

    def create_ui(self):
        """建立對話框UI"""
        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 標題
        title_label = ttk.Label(
            main_frame,
            text=f"發現 {len(self.similar_questions)} 道近似題目，請選擇要保留的版本：",
            font=('Arial', 12, 'bold')
        )
        title_label.pack(pady=10)

        # 建立滾動區域
        canvas = tk.Canvas(main_frame)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 儲存選擇
        self.choice_var = tk.IntVar(value=0)

        # 顯示新題目
        self.create_question_card(scrollable_frame, 0, "新題目", self.new_question,
                                  similarity=None, is_new=True)

        # 顯示近似題目
        for idx, (similar_q, similarity) in enumerate(self.similar_questions, 1):
            self.create_question_card(scrollable_frame, idx,
                                     f"已存在題目 (ID: {similar_q['id']})",
                                     similar_q, similarity, is_new=False)

        # 按鈕區
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=10)

        ttk.Button(button_frame, text="確認選擇", command=self.confirm_choice).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="全部保留（新增）", command=self.add_as_new).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="跳過", command=self.skip).pack(side=tk.LEFT, padx=5)

    def create_question_card(self, parent, index, title, question_data, similarity, is_new):
        """
        建立題目卡片

        Args:
            parent: 父容器
            index: 索引（用於單選按鈕）
            title: 標題
            question_data: 題目資料或新題目字典
            similarity: 相似度（None 表示新題目）
            is_new: 是否為新題目
        """
        card_frame = ttk.LabelFrame(parent, text=title, padding="10")
        card_frame.pack(fill=tk.X, padx=10, pady=5)

        # 頂部資訊區（單選按鈕和圖片連結）
        top_frame = ttk.Frame(card_frame)
        top_frame.pack(fill=tk.X, pady=2)

        # 單選按鈕
        radio = ttk.Radiobutton(top_frame, text="選擇此版本", variable=self.choice_var, value=index)
        radio.pack(side=tk.LEFT)

        # 圖片連結
        if is_new:
            image_path = self.image_path
        else:
            image_path = question_data.get('image_path', '')

        if image_path and os.path.exists(image_path):
            image_link = tk.Label(
                top_frame,
                text="📷 查看圖片",
                fg="blue",
                cursor="hand2",
                font=('Arial', 9, 'underline')
            )
            image_link.pack(side=tk.LEFT, padx=20)
            # 綁定點擊事件
            image_link.bind("<Button-1>", lambda e, path=image_path: self.open_image(path))
        else:
            ttk.Label(top_frame, text="(無圖片)", foreground='gray').pack(side=tk.LEFT, padx=20)

        # 相似度顯示
        if similarity is not None:
            similarity_label = ttk.Label(
                card_frame,
                text=f"相似度: {similarity:.2%}",
                font=('Arial', 10, 'bold'),
                foreground='red' if similarity > 0.9 else 'orange'
            )
            similarity_label.pack(anchor=tk.W, pady=2)

        # 題目內容
        if is_new:
            question_text = self.new_question['question']
            options = self.new_question['options']
        else:
            question_text = question_data['question']
            options = question_data['options']

        ttk.Label(card_frame, text=f"題目: {question_text}", wraplength=800).pack(anchor=tk.W, pady=2)

        # 選項
        options_text = "  ".join([f"{k}.{v}" for k, v in sorted(options.items())])
        ttk.Label(card_frame, text=f"選項: {options_text}", wraplength=800).pack(anchor=tk.W, pady=2)

        # 如果是已存在的題目，顯示正確答案
        if not is_new and question_data.get('correct_answer'):
            ttk.Label(
                card_frame,
                text=f"正確答案: {question_data['correct_answer']}",
                foreground='green'
            ).pack(anchor=tk.W, pady=2)

    def confirm_choice(self):
        """確認選擇"""
        choice = self.choice_var.get()

        if choice == 0:
            # 選擇新題目，強制添加
            self.add_as_new()
        else:
            # 選擇已存在題目，跳過不添加
            selected_q = self.similar_questions[choice - 1][0]
            self.log_callback(f"選擇保留已存在題目 (ID: {selected_q['id']})，跳過新題目")
            self.dialog.destroy()

    def add_as_new(self):
        """將新題目添加為新題目"""
        question_id = self.db.force_add_question(
            question=self.new_question['question'],
            options=self.new_question['options'],
            correct_answer=self.new_question.get('correct_answer', ''),
            source=self.source,
            image_path=self.image_path
        )
        self.log_callback(f"新增題目 ID: {question_id}")
        self.refresh_callback()
        self.dialog.destroy()

    def skip(self):
        """跳過此題目"""
        self.log_callback("使用者選擇跳過此題目")
        self.dialog.destroy()

    def open_image(self, image_path):
        """
        開啟圖片

        Args:
            image_path: 圖片路徑
        """
        if not os.path.exists(image_path):
            messagebox.showerror("錯誤", "圖片檔案不存在")
            return

        # 使用系統預設程式開啟圖片
        try:
            if platform.system() == 'Windows':
                os.startfile(image_path)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', image_path])
            else:  # Linux
                subprocess.run(['xdg-open', image_path])
        except Exception as e:
            messagebox.showerror("錯誤", f"無法開啟圖片: {e}")


def main():
    root = tk.Tk()
    app = QuestionExtractorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

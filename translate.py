import requests
import json
import time
import os
import csv
from typing import Tuple
from collections import defaultdict

# GLM大模型API配置
API_URL = "https://cloud.infini-ai.com/maas/v1/chat/completions"
API_KEY = "sk-kg4pdmnoy5nxvzys"
MODEL = "qwen2.5-7b-instruct"

class GLMTranslator:
    """GLM翻译器类（用于翻译英文到中文）"""
    
    def __init__(self):
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }
        self.model = MODEL
        self.request_count = 0
        self.start_time = time.time()
    
    def translate(self, text: str, max_retries: int = 3) -> str:
        """使用GLM大模型将英文文本翻译成中文"""
        # 空文本直接返回
        if not text.strip():
            return ""
        
        # 速率控制：每60秒最多100个请求
        self.request_count += 1
        elapsed_time = time.time() - self.start_time
        
        if self.request_count >= 100 and elapsed_time < 60:
            sleep_time = 60 - elapsed_time + 1
            print(f"速率控制：等待 {sleep_time:.1f} 秒...")
            time.sleep(sleep_time)
            self.request_count = 1
            self.start_time = time.time()
        elif elapsed_time >= 60:
            self.request_count = 1
            self.start_time = time.time()
        
        # 构建翻译指令
        translation_prompt = f"请将以下英文文本准确翻译成中文，保持原意和语气不变，不要添加额外内容：\n{text}"
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": translation_prompt
                        }
                    ]
                }
            ],
            "temperature": 0.1,  # 降低随机性，保证翻译准确性
            "max_tokens": 1000
        }
        
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    url=API_URL,
                    headers=self.headers,
                    data=json.dumps(payload, ensure_ascii=False),
                    timeout=60
                )
                response.raise_for_status()
                result = response.json()
                
                # 提取翻译结果
                if "choices" in result and len(result["choices"]) > 0:
                    message = result["choices"][0].get("message", {})
                    content = message.get("content", "").strip()
                    
                    # 清理可能的格式冗余
                    if content.startswith("翻译："):
                        content = content[3:].strip()
                    return content
                
                return text
                
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    wait_time = 2 * (attempt + 1)
                    print(f"翻译超时，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                    continue
                print(f"翻译超时，返回原文本: {text[:30]}...")
                return text
                
            except requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    wait_time = 2 * (attempt + 1)
                    print(f"连接错误，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                    continue
                print(f"连接错误，返回原文本: {text[:30]}...")
                return text
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    wait_time = 30 * (attempt + 1)
                    print(f"API请求限制，等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                print(f"HTTP错误 (状态码 {e.response.status_code}): {text[:30]}...")
                return text
                
            except Exception as e:
                print(f"翻译错误: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return text
        
        return text

def process_csv_file(input_csv: str, output_csv: str, translator: GLMTranslator):
    """
    处理单个CSV文件（支持断点续跑）：提取direct_utterance/indirect_utterance并翻译
    """
    # 步骤1：读取输入CSV（处理BOM编码），保存所有原始记录
    print(f"\n正在读取文件: {input_csv}")
    input_rows = []
    try:
        with open(input_csv, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            # 验证必要字段
            required_fields = ["direct_utterance", "indirect_utterance"]
            for field in required_fields:
                if field not in reader.fieldnames:
                    print(f"错误：CSV缺少必要字段 '{field}'")
                    return
            # 读取所有数据行（保存为列表，方便按索引定位）
            input_rows = list(reader)
        total_records = len(input_rows)
        print(f"成功读取 {total_records} 条原始记录")
    except Exception as e:
        print(f"读取CSV失败: {str(e)}")
        return
    
    # 步骤2：判断断点位置，确定开始处理的索引（start_idx）
    output_fields = [
        "direct_utterance",    # 原英文直接表达
        "direct_utterance_zh", # 翻译后中文直接表达
        "indirect_utterance",  # 原英文间接表达
        "indirect_utterance_zh"# 翻译后中文间接表达
    ]
    start_idx = 0  # 默认从第0条开始（新文件）
    
    if os.path.exists(output_csv):
        # 若输出文件已存在，读取已处理的记录数（减去表头1行）
        try:
            with open(output_csv, 'r', encoding='utf-8') as f:
                existing_reader = csv.reader(f)
                existing_rows = list(existing_reader)
                # 已处理记录数 = 现有行数 - 1（表头行）
                processed_records = len(existing_rows) - 1 if len(existing_rows) > 0 else 0
                
                if processed_records > 0:
                    if processed_records >= total_records:
                        print(f"提示：输出文件已包含所有记录（{processed_records}条），无需重复处理")
                        return
                    start_idx = processed_records
                    print(f"检测到已有输出文件，已处理 {processed_records} 条，将从第 {start_idx + 1} 条开始续跑")
                else:
                    print(f"检测到输出文件已存在，但无有效数据，将从头开始处理")
        except Exception as e:
            print(f"读取现有输出文件失败，将从头开始处理：{str(e)}")
    
    # 步骤3：以追加模式打开输出文件，开始处理（从start_idx开始）
    print(f"开始翻译 {input_csv} 中的字段（断点续跑，从第 {start_idx + 1} 条开始）...")
    with open(output_csv, 'a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        
        # 若为新文件（无已处理记录），先写入表头
        if start_idx == 0:
            writer.writeheader()
            print("已写入CSV表头")
        
        # 步骤4：从断点索引开始，处理剩余记录
        for idx in range(start_idx, total_records):
            row = input_rows[idx]
            current_record_num = idx + 1  # 人类可读的记录编号（从1开始）
            
            # 提取并翻译字段
            direct_en = row["direct_utterance"].strip()
            indirect_en = row["indirect_utterance"].strip()
            
            direct_zh = translator.translate(direct_en)
            indirect_zh = translator.translate(indirect_en)
            
            # 追加写入当前记录（不会覆盖已有数据）
            writer.writerow({
                "direct_utterance": direct_en,
                "direct_utterance_zh": direct_zh,
                "indirect_utterance": indirect_en,
                "indirect_utterance_zh": indirect_zh
            })
            
            # 显示进度（每10条打印一次，或最后一条记录）
            if current_record_num % 10 == 0 or current_record_num == total_records:
                print(f"  已处理 {current_record_num}/{total_records} 条")
    
    print(f"当前文件处理完成（断点续跑结束），结果保存到: {output_csv}")

def main():
    """主函数：处理train.csv和test.csv（支持断点续跑）"""
    print("=" * 60)
    print("CSV字段翻译程序（支持断点续跑，仅处理direct/indirect_utterance）")
    print("=" * 60)
    
    # 配置文件路径
    input_files = {
        "train": "train.csv",
        "test": "test.csv"
    }
    output_dir = "translated_utterances"
    os.makedirs(output_dir, exist_ok=True)
    
    # 初始化翻译器
    translator = GLMTranslator()
    start_time = time.time()
    
    try:
        # 处理每个CSV文件
        for file_type, input_path in input_files.items():
            if not os.path.exists(input_path):
                print(f"警告：{input_path} 不存在，跳过")
                continue
            
            output_path = os.path.join(output_dir, f"translated_{file_type}.csv")
            process_csv_file(input_path, output_path, translator)
        
        # 统计耗时
        elapsed = time.time() - start_time
        print(f"\n所有文件处理完成！总耗时: {elapsed:.1f}秒")
        print(f"翻译结果目录：{output_dir}")
        
    except KeyboardInterrupt:
        print("\n\n用户中断程序（断点已保存）")
        print("下次运行程序将自动从当前中断位置继续翻译，无需从头开始")
    except Exception as e:
        print(f"\n程序错误: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
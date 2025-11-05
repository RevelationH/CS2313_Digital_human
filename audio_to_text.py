import speech_recognition as sr
import msvcrt  # 用于检测按键输入

class SpeechToTextConverter:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.audio_data = None  # 存储音频数据
        self.text = None

    def start_recording(self):
        """
        开始录音
        """
        with sr.Microphone() as source:
            print("开始录音...")
            self.recognizer.adjust_for_ambient_noise(source)  # 调整麦克风的环境噪音
            self.audio_data = self.recognizer.listen(source)  # 开始录音
        self.convert_to_text()  # 识别语音

    def convert_to_text(self):
        """
        将音频转换为文本
        """
        if self.audio_data:
            try:
                self.text = self.recognizer.recognize_google(
                    self.audio_data,
                    language="zh-CN,en-US"
                )
                print("识别结果：", self.text)
                return self.text
            except sr.UnknownValueError:
                print("无法识别语音输入。")
                return None
            except sr.RequestError as e:
                print(f"请求语音识别服务失败：{e}")
                return False
        else:
            print("没有音频数据！")

    def save_text(self, text):
        """
        保存文本到变量
        """
        print("收到的文本已存储。按回车键退出：")
        input()  # 等待用户输入以防止程序立即退出

# 使用示例
converter = SpeechToTextConverter()
converter.start_recording()
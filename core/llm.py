import ollama

class LLM:
    def query(self, prompt: str):
        response = ollama.chat(model="llama3.2:1b", messages=[{"role": "user", "content": prompt}])
        return response['message']['content']

    # NOTE: For Hailo acceleration, use llama.cpp with Hailo backend or official Hailo LLM examples

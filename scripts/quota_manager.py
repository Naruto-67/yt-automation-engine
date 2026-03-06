def generate_text(self, prompt, task_type="creative"):
        state = self._get_active_state()
        usage = state.get("gemini_used", 0)
        
        # 🚨 NEW: Explicitly route Community Management to Groq
        if task_type == "comment_reply":
            print("⚡ [ROUTER] Routing 'COMMENT_REPLY' strictly to Groq Llama 3.3...")
            return groq_client.generate_text(prompt, role="commenter"), "Groq Llama 3.3"

        if self.gemini_blocked_for_run:
            print(f"⚠️ [ROUTER] Gemini is resting. Auto-routing '{task_type.upper()}' to Groq Fallback.")
            return groq_client.generate_text(prompt, role=task_type), "Groq Llama 3.3"

        print(f"🛡️ [ROUTER] Attempting '{task_type.upper()}' via {self.TEXT_MODELS[0]}...")
        
        if usage < self.gemini_text_limit:
            from google import genai
            client = genai.Client(api_key=self.gemini_key)
            
            for model_name in self.TEXT_MODELS:
                try:
                    response = client.models.generate_content(
                        model=model_name, 
                        contents=prompt
                    )
                    self.consume_points("gemini", 1)
                    print("⏳ [ROUTER] Pacing API to avoid RPM bans (Sleeping 4s)...")
                    time.sleep(4)
                    return response.text, model_name
                    
                except Exception as e:
                    error_msg = str(e).lower()
                    if "404" in error_msg or "not found" in error_msg:
                        continue 
                    elif "429" in error_msg or "quota" in error_msg or "exhausted" in error_msg:
                        print(f"⚠️ [ROUTER] Gemini 429 RPM Limit Hit on {model_name}!")
                        self.gemini_blocked_for_run = True
                        break 
                    else:
                        print(f"❌ [GEMINI] Non-rate-limit error on {model_name}: {e}")
                        break
        else:
            print(f"⚠️ [ROUTER] 50/50 Rule Limit Reached ({usage}/{self.gemini_text_limit}).")
            self.gemini_blocked_for_run = True 
            
        print("⚡ [ROUTER] Executing Fallback Protocol (Groq)...")
        fallback_text = groq_client.generate_text(prompt, role=task_type)
        return fallback_text, "Groq Llama 3.3"

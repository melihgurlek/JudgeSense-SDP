import os
from typing import List, Dict, Any, Optional
import pandas as pd
from dataclasses import dataclass
import json
from concurrent.futures import ThreadPoolExecutor
import asyncio
from enum import Enum
import aiohttp
import logging
from datetime import datetime


class AgentType(Enum):
    CHATGPT = "chatgpt"
    GOOGLE_AI = "google_ai"
    DEEPSEEK = "deepseek"


@dataclass
class AgentConfig:
    agent_type: AgentType
    api_key: str
    api_url: str
    model: str
    temperature: float
    max_tokens: int


class LegalAgent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.session = aiohttp.ClientSession()

    async def close(self):
        await self.session.close()

    async def analyze_case(self, case_text: str) -> Dict[str, Any]:
        """Analyze a legal case using the specific AI model"""
        try:
            headers = self._get_headers()
            payload = self._prepare_payload(case_text)

            # For Google AI, append the API key to the URL rather than in headers
            url = self.config.api_url
            if self.config.agent_type == AgentType.GOOGLE_AI:
                url = f"{url}?key={self.config.api_key}"

            async with self.session.post(url, json=payload, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logging.error(
                        f"API error for {self.config.agent_type}: Status {response.status}, Response: {error_text}")
                    return {"error": f"API error: {response.status}"}

                response_data = await response.json()
                return self._parse_response(response_data)

        except Exception as e:
            logging.error(
                f"Error in {self.config.agent_type} analysis: {str(e)}")
            return {"error": str(e)}

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json"
        }

        # Add specific headers for each API
        if self.config.agent_type == AgentType.GOOGLE_AI:
            # No Authorization header needed for Google AI - we'll append the key to the URL
            pass
        else:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        return headers

    def _prepare_payload(self, case_text: str) -> Dict:
        prompt = self._get_system_prompt() + "\n\nCase to analyze:\n" + case_text

        if self.config.agent_type == AgentType.CHATGPT:
            return {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": case_text}
                ],
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens
            }
        elif self.config.agent_type == AgentType.GOOGLE_AI:
            return {
                "contents": [{
                    "role": "user",
                    "parts": [{"text": prompt}]
                }],
                "generation_config": {
                    "temperature": self.config.temperature,
                    "max_output_tokens": self.config.max_tokens,
                    "top_p": 0.8,
                    "top_k": 40
                }
            }
        else:  # DEEPSEEK
            return {
                "model": self.config.model,
                "prompt": prompt,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens
            }

    def _get_system_prompt(self) -> str:
        return """As a legal analysis expert, analyze this case in Turkish and provide:
1. Temel Hukuki İlkeler (Key Legal Principles)
2. Ana Argümanlar (Main Arguments)
3. Karar Gerekçesi (Decision Rationale)
4. İlgili İçtihatlar (Relevant Precedents)
5. Hukuk Öğrencileri için Öğrenme Noktaları (Learning Points for Law Students)

Please structure your response using these headings and provide detailed analysis under each."""

    def _parse_response(self, response_data: Dict) -> Dict[str, Any]:
        try:
            if self.config.agent_type == AgentType.CHATGPT:
                return {"analysis": response_data["choices"][0]["message"]["content"]}
            elif self.config.agent_type == AgentType.GOOGLE_AI:
                # Google AI Studio response parsing
                if "error" in response_data:
                    return {"error": response_data["error"]["message"]}
                return {"analysis": response_data["candidates"][0]["content"]["parts"][0]["text"]}
            else:  # DEEPSEEK
                return {"analysis": response_data["choices"][0]["text"]}
        except Exception as e:
            logging.error(
                f"Error parsing {self.config.agent_type} response: {str(e)}")
            return {"error": f"Failed to parse response: {str(e)}"}


class JurySaneSystem:
    def __init__(self, agent_configs: List[AgentConfig], data_path: str):
        self.agents = {config.agent_type: LegalAgent(
            config) for config in agent_configs}
        self.data_path = data_path
        self.cases_df = pd.read_csv(data_path)

    async def analyze_case_multi_agent(self, case_idx: int) -> Dict[str, Any]:
        """Analyze a single case using all agents and combine their insights"""
        case_text = self.cases_df.iloc[case_idx]["Explanation"]

        # Get analysis from all agents concurrently
        tasks = []
        for agent_type, agent in self.agents.items():
            tasks.append(asyncio.create_task(agent.analyze_case(case_text)))

        results = await asyncio.gather(*tasks)

        # Combine and compare analyses
        combined_analysis = {
            "case_metadata": {
                "court": self.cases_df.iloc[case_idx]["Court Name"],
                "case_number": self.cases_df.iloc[case_idx]["Case Number"],
                "decision_date": self.cases_df.iloc[case_idx]["Decision Date"]
            },
            "agent_analyses": {
                agent_type.value: result
                for agent_type, result in zip(self.agents.keys(), results)
            },
            "analysis_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        return combined_analysis

    async def analyze_batch(self, start_idx: int, batch_size: int) -> List[Dict[str, Any]]:
        """Analyze a batch of cases using all agents"""
        tasks = []
        for idx in range(start_idx, min(start_idx + batch_size, len(self.cases_df))):
            tasks.append(self.analyze_case_multi_agent(idx))
        return await asyncio.gather(*tasks)

    async def close(self):
        """Close all agent sessions"""
        for agent in self.agents.values():
            await agent.close()


async def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('multi_agent.log'),
            logging.StreamHandler()
        ]
    )

    # Load API keys from environment variables
    agent_configs = [
        AgentConfig(
            agent_type=AgentType.CHATGPT,
            api_key="API_KEY",
            api_url="https://api.openai.com/v1/chat/completions",
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=2000
        ),
        AgentConfig(
            agent_type=AgentType.GOOGLE_AI,
            api_key="API_KEY",
            api_url="https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent",
            model="gemini-pro",
            temperature=0.7,
            max_tokens=2000
        ),
        AgentConfig(
            agent_type=AgentType.DEEPSEEK,
            api_key="API_KEY",
            api_url="https://api.deepseek.com/v1/completions",
            model="deepseek-chat",
            temperature=0.7,
            max_tokens=2000
        )
    ]

    # Initialize JurySane system
    jurysane = JurySaneSystem(agent_configs, "legal_cases.csv")

    try:
        # Analyze first 10 cases as a test
        logging.info("Starting batch analysis...")
        results = await jurysane.analyze_batch(0, 10)

        # Save results
        output_file = f"multi_agent_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        logging.info(f"Analysis complete. Results saved to {output_file}")

    except Exception as e:
        logging.error(f"Error during analysis: {str(e)}")
    finally:
        await jurysane.close()

if __name__ == "__main__":
    asyncio.run(main())

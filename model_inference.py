import requests
from decouple import config


class TogetherEvalModel:
    def __init__(
        self,
        together_api_key,
        # together_key_path
    ):
        self.together_api_key = together_api_key
        # self.together_key_path = together_key_path
        # with open(together_key_path, "r") as f:
        #     self.together_api_key = f.read().strip()

    def eval(self, prompt, num_tokens=512, return_true_logprob=False):
        gen_args = {
            "model": "mistralai/Mixtral-8x7B-Instruct-v0.1",
            "prompt": prompt,
            "temperature": 0,
            "max_tokens": num_tokens,
            "repetition_penalty": 1,
            "logprobs": 1,  # Request log probabilities to calculate true logprob
        }

        r = requests.post(
            "https://api.together.xyz/inference",
            json=gen_args,
            headers={
                "Authorization": "Bearer " + self.together_api_key,  # type: ignore
            },
        )

        # Handle the response
        try:
            response = r.json()
            output_text = response["output"]["choices"][0]["text"]
            if return_true_logprob:
                true_logprob = response["output"]["choices"][0].get("logprobs", {}).get("token_logprobs", [])
                return output_text, true_logprob
            else:
                return output_text
        except Exception as e:
            print(f"Error processing the request: {e}")
            return None


if __name__ == "__main__":
    prompt = """
Based on the ingredient list below, is this a vegetarian, pescatarian, starter or dessert recipe?
Output ONE WORD ONLY!

Ingredients:
500gr flour
5 eggs
Salt
400gr porcini
1 x garlic
40gr olive oil
150 vegetable stock
35g butter unsalted
15g parsley
Salt & pepper
    """
    together_model = TogetherEvalModel(config("TOGETHER_KEY"))
    result = together_model.eval(prompt=prompt, num_tokens=16)
    print(result.strip().split("\n")[1])

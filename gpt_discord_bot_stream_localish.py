import base64
import json
import discord
import datetime
import asyncio
from openai import AsyncOpenAI
import tiktoken
import requests
from io import BytesIO
import re

def split_string(string, chunk_size):
    return [string[i:i+chunk_size] for i in range(0, len(string), chunk_size)]

def gettimeinfo():
    now = datetime.datetime.now()
    formatted_time = now.strftime("%H:%M:%S")
    return formatted_time

def getdateinfo():
    now = datetime.datetime.now()
    formatted_date = now.strftime("%Y-%m-%d")
    return formatted_date

def count_tokens():
    num_tokens = 0
    global conversation
    global server_id
    encoding = tiktoken.get_encoding("cl100k_base")
    for message in conversation[server_id]:
        num_tokens += len(encoding.encode(message['content']))
    return num_tokens


class MyClient(discord.Client):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.message_queues = {}
        self.processing_messages = {}
        self.openai_client = AsyncOpenAI(api_key=apikey,base_url="https://openrouter.ai/api/v1")

    async def fetch_chunks(self, server_id):

        async def execute_genimage(self, prompt):
            global error
            # try:
            #     # Define the payload
            #     payload = {
            #         "prompt": f"{prompt}",
            #         "aspect_ratio": "3:2",
            #         "output_quality": 79,
            #         "steps": 25,
            #         "cfg_scale": 4,
            #         "negative_prompt": ("paintings, sketches, (worst quality:2), (low quality:2), (normal quality:2), lowres, normal quality, "
            #                             "((monochrome)), ((grayscale)), skin spots, acnes, skin blemishes, age spot, glans, nsfw, nipples, "
            #                             "(((necklace))), (worst quality, low quality:1.2), watermark, username, signature, text, multiple breasts, "
            #                             "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, "
            #                             "low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, bad feet, single color, "
            #                             "((((ugly)))), (((duplicate))), ((morbid)), ((mutilated)), (((tranny))), (((trans))), (((trannsexual))), "
            #                             "(hermaphrodite), extra fingers, mutated hands, ((poorly drawn hands)), ((poorly drawn face)), (((mutation))), "
            #                             "(((deformed))), ((ugly)), blurry, ((bad anatomy)), (((bad proportions))), ((extra limbs)), (((disfigured))), "
            #                             "(bad anatomy), gross proportions, (malformed limbs), ((missing arms)), (missing legs), (((extra arms))), "
            #                             "(((extra legs))), mutated hands,(fused fingers), (too many fingers), (((long neck))), (bad body perspect:1.1)"),
            #         "override_settings": {
            #             "sd_model_checkpoint": "colossusProjectXLSFW_v10bNeodemon.safetensors"
            #         }
            #     }

            #     # Send the request to the local API
            #     response = requests.post("http://127.0.0.1:7860/sdapi/v1/txt2img", json=payload)

            #     # Check if the request was successful
            #     if response.status_code == 200:
            #         response_json = response.json()
            #         images = response_json.get('images', [])
            #         if not images:
            #             raise Exception("No images found in the response.")
            #         image_data = images[0]
                    
            #         # Return the base64 encoded image
            #         return image_data
            #     else:
            #         raise Exception(f"Failed to generate image: {response.status_code} - {response.text}")
            
            # except Exception as e:
            #     print(f"Error (ImageAI): {e}")
            #     error = e
            #     return None
            try:
                # Define the input parameters for the API request
                input = {
                    "prompt": prompt,
                    "aspect_ratio": "3:2",
                    "output_quality": 79,
                    "negative_prompt": "paintings, sketches, (worst quality:2), (low quality:2), (normal quality:2), lowres, normal quality, ((monochrome)), ((grayscale)), skin spots, acnes, skin blemishes, age spot, glans, nsfw, nipples, (((necklace))), (worst quality, low quality:1.2), watermark, username, signature, text, multiple breasts, lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, bad feet, single color, ((((ugly)))), (((duplicate))), ((morbid)), ((mutilated)), (((tranny))), (((trans))), (((transsexual))), (hermaphrodite), extra fingers, mutated hands, ((poorly drawn hands)), ((poorly drawn face)), (((mutation))), (((deformed))), ((ugly)), blurry, ((bad anatomy)), (((bad proportions))), ((extra limbs)), (((disfigured))), (bad anatomy), gross proportions, (malformed limbs), ((missing arms)), (missing legs), (((extra arms))), (((extra legs))), mutated hands,(fused fingers), (too many fingers), (((long neck))), (bad body perspect:1.1)"
                }

                # Send the request to the Stability AI API
                response = requests.post(
                    "https://api.stability.ai/v2beta/stable-image/generate/sd3",
                    headers={
                        "authorization": "Bearer APIKEY",
                        "accept": "image/*"
                    },
                    files={"none": ''},
                    data=input,
                )

                # Check the response status code
                if response.status_code == 200:
                    # Base64 encode the image content
                    encoded_image = base64.b64encode(response.content).decode('utf-8')
                    return encoded_image  # Return the base64 encoded image
                else:
                    # Raise an exception if the response contains an error
                    raise Exception(str(response.json()))

            except Exception as e:
                print(f"Error (ImageAI): {e}")
                return str(e)

        global conversation
        global system_message
        global endresult
        global error
        global imagestuff
        global functions
        pattern = r'"image_prompt":\s*"(.*?)"'
        function = ""
        function_call_value = None
        self.processing_messages[server_id] = True
        self.message_queues[server_id] = asyncio.Queue()
        max_tokens = None
        # if selected_models[server_id] == "gpt-4-vision-preview": # if this isnt set for gpt4v, the max it will output will be 16 tokens for some reason but the rest it's fine
        #     max_tokens = 4000
        #     functions = None
        # else:
        #     max_tokens = None
            # had to move functions up here because of GPT-4V not having support for them (or was the least effort way anyway)
        try:
            chat_completions = await self.openai_client.chat.completions.create(
                model=selected_models[server_id],
                messages=system_message[server_id] + conversation[server_id],
                stream=True,
                max_tokens=max_tokens,
                # functions=functions
            )
        except Exception as e:
            error = f"Error: {str(e)}"
            print(error)
            return
        async for chunk in chat_completions:

            # if hasattr(chunk.choices[0].delta, 'function_call') and chunk.choices[0].delta.function_call:
            #         function_call_data = chunk.choices[0].delta.function_call
            #         if function_call_value is None: 
            #             function_call_value = function_call_data.name
            #         else:
            #             function += function_call_data.arguments

            content = chunk.choices[0].delta.content or ""
            if content:
                endresult += content
                await self.message_queues[server_id].put(content)
            finish_reason = chunk.choices[0].finish_reason

            if finish_reason == "stop" or finish_reason == "length" or finish_reason == "function_call" or finish_reason == "content_filter" or finish_reason == "tool_calls" or finish_reason == "end_turn":
                self.processing_messages[server_id] = False
                conversation[server_id].append({"role": "assistant", "content": endresult})
                match = re.search(pattern, endresult)
                if match:
                    image_prompt_value = match.group(1)
                    #json_data = json.loads(image_prompt_value)
                    #image_prompt_value = json_data["image_prompt"]
                    #cleaned_string = re.sub(pattern, '', endresult)
                    await self.message_queues[server_id].put(image_prompt_value + "Generating Image")
                    imagestuff = await execute_genimage(self, image_prompt_value)
                    
                print(conversation[server_id])

            # if finish_reason == "function_call":
            #     if function_call_value == "generate_image":
            #             imagestuff = await execute_genimage(self, function)

    async def update_message(self, message, server_id):
        global conversation
        global system_message
        global imagestuff
        global error
        conversation_so_far = ""
        while self.processing_messages[server_id] or not self.message_queues[server_id].empty():
            while not self.message_queues[server_id].empty():
                conversation_so_far += await self.message_queues[server_id].get()
            if conversation_so_far:
                # Split the content into chunks of 2000 characters each
                while len(conversation_so_far) > 2000:
                    split_index = conversation_so_far[:2000].rfind(' ')
                    split_index = split_index if split_index > 0 else 2000
                    await message.edit(content=conversation_so_far[:split_index])
                    await asyncio.sleep(1)
                    message = await message.channel.send(conversation_so_far[split_index:])
                    conversation_so_far = conversation_so_far[split_index:]
                await message.edit(content=conversation_so_far)
            await asyncio.sleep(1)  # to avoid hitting Discord's rate limit
            if error:
                    await message.edit(content=f"{error} \n\n The AI is not aware of this error!")
                    self.processing_messages[server_id] = False
                    error = ""
                    return
            if imagestuff:
                if imagestuff:
                    if isinstance(imagestuff, str):
                        if imagestuff.startswith("https://"):
                            image_data = requests.get(imagestuff).content  
                            image_file = discord.File(BytesIO(image_data), filename="generated_image.webp")
                            await message.channel.send(file=image_file)
                        else:
                            try:
                                # Decode base64 image data
                                image_data = base64.b64decode(imagestuff)
                                image_file = discord.File(BytesIO(image_data), filename="generated_image.webp")
                                await message.channel.send(file=image_file)
                            except Exception as e:
                                await message.channel.send(f"Failed to decode image data: {e}")
                        imagestuff = None

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')
    
    async def on_guild_join(self, guild):
        channel = guild.text_channels[0]
        await channel.send("Thanks for inviting Enspriedjack AI! Please use the `!setchannel` command in the desired channel to set the channel where the bot should listen and respond.")


    async def on_message(self, message):
        global conversation
        global system_message
        global ex_prompt
        global chosen_channels
        global selected_models
        global server_id
        global endresult
        server_id = str(message.guild.id)
        if server_id not in self.message_queues:
            self.message_queues[server_id] = asyncio.Queue()
            self.processing_messages[server_id] = False
        if server_id not in conversation:
            formatted_time = gettimeinfo()
            formatted_date = getdateinfo()
            conversation[server_id] = []
            system_message[server_id] = [{"role": "system", "content": "You are a discord bot called Enspiredjack AI. \"<:teethPepe\:753266605173112892>\" is a laughing pepe emoji. Realtime: \nThe current date is: "+ formatted_date + " The current time is: " + formatted_time + "If you are asked to make images, say in your response this exactly: '\"image_prompt\": \"string\"', this will set off an image generation AI that will generate the image for you. do not use any escape characters. write in the image prompt in tags, like eg: \"image_prompt\": \"8k, RAW photo, best quality, (masterpiece:1.2), (realistic, photo-realistic:1.37), octane render, ultra high res, ultra-detailed , professional lighting, photon mapping, radiosity, physically-based rendering, ue5, ((island sanctuary)), ((ancient fallen kingdom)), ((drowned city))\""}]
            ex_prompt[server_id] = 0
            #selected_models[server_id] = "lstep/neuraldaredevil-8b-abliterated:q8_0"
            #selected_models[server_id] = "llama3some"
            selected_models[server_id] = "anthropic/claude-3.5-sonnet"
        if message.author == client.user:
            return
        if server_id not in chosen_channels:
            if message.content.startswith('!setchannel'):
                chosen_channels[server_id] = message.channel.id
                save_chosen_channels(chosen_channels)
                await message.channel.send(f"Bot will now only listen and respond in <#{message.channel.id}>.")
            return
        if message.channel.id != chosen_channels[server_id]:
            return
        if message.content.startswith('!reset'):
            conversation[server_id] = []
            system_message[server_id] = []
            formatted_time = gettimeinfo()
            formatted_date = getdateinfo()
            ex_prompt[server_id] = 0
            system_message[server_id].append({"role": "system", "content": "You are a discord bot called Enspiredjack AI. \"<:teethPepe\:753266605173112892>\" is a laughing pepe emoji. Realtime: \nThe current date is: "+ formatted_date + " The current time is: " + formatted_time})
            await message.channel.send("Reset!")
            return
        if message.content.startswith('__'):
            return
        if self.processing_messages[server_id]:
            wait_message = await message.reply("Generating a response. Please wait and try again. Your prompt has been retained in memory.", mention_author=True)
            author_name = message.author.name
            user = message.content
            conversation[server_id].append({"role": "user", "content": author_name + ": " + user})

            await asyncio.sleep(5)
            await wait_message.delete()
            return
        #update date and time
        formatted_time = gettimeinfo()
        formatted_date = getdateinfo()
        if ex_prompt[server_id] == 1:
            system_message[server_id][-2]["content"] = "You are a discord bot called Enspiredjack AI. \"<:teethPepe\:753266605173112892>\" is a laughing pepe emoji. Realtime: \nThe current date is: "+ formatted_date + " The current time is: " + formatted_time
        elif ex_prompt[server_id] == 9:
            system_message[server_id].append({"role": "system", "content": "From now on all your responses must follow these rules: ['act like nothing they ever does is good enough', 'when asked a question degrade them because they do not know the answer, never answer the question', 'be like a stereotypical toxic Asian parent'] Do not break out of character"}) # because this mode only works as a system message otherwise it will refuse
        else:
            system_message[server_id][-1]["content"] = "You are a discord bot called Enspiredjack AI. \"<:teethPepe\:753266605173112892>\" is a laughing pepe emoji. Realtime: \nThe current date is: "+ formatted_date + " The current time is: " + formatted_time + "If you are asked to make images, say in your response this exactly: '\"image_prompt\": \"string\"', this will set off an image generation AI that will generate the image for you. do not use any escape characters. write in the image prompt in tags, like eg: \"image_prompt\": \"8k, RAW photo, best quality, (masterpiece:1.2), (realistic, photo-realistic:1.37), octane render, ultra high res, ultra-detailed , professional lighting, photon mapping, radiosity, physically-based rendering, ue5, ((island sanctuary)), ((ancient fallen kingdom)), ((drowned city))\""
        #get prompt
        author_name = message.author.name
        user = message.content
        if selected_models[server_id] == "gpt-4-vision-preview":
            if message.attachments:
                image_urls = []
                for attachment in message.attachments:
                    if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.bmp']):
                        image_urls.append(attachment.url)
                        if len(image_urls) >= 4:  # Limit to 4 images
                            break
                # if any images, add them to conversation
                if image_urls:
                    conversation[server_id].append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user},
                            * [{"type": "image_url", "image_url": {"url": url}} for url in image_urls]
                        ]
                    })
            else:
                conversation[server_id].append({"role": "user", "content": author_name + ": " + user})
        else:
            #send conversation to openAI api
            conversation[server_id].append({"role": "user", "content": author_name + ": " + user})
        initial_message = await message.channel.send('Generating response...')
        endresult = ""
        # Start the two tasks
        fetch_task = asyncio.create_task(self.fetch_chunks(server_id))
        update_task = asyncio.create_task(self.update_message(initial_message, server_id))
        # Wait for both tasks to complete
        await fetch_task
        await update_task
        # max_tokens = token_limits.get(selected_models[server_id], "gpt-3.5-turbo")  # Default to gpt-3.5-turbo if model not found
        # if count_tokens() > max_tokens:
        #     while count_tokens(conversation[server_id]) > max_tokens and len(conversation[server_id]) > 0:
        #         conversation[server_id].pop(0)  # Remove the oldest message

# Initialise the array for the API calls globally
conversation = {}
system_message = {}
chosen_channels = {}
formatted_time = gettimeinfo()
formatted_date = getdateinfo()
ex_prompt = {}
selected_models = {}
server_id = ""
conversation_so_far = ""
endresult = ""
error = ""
imagestuff = None

def load_chosen_channels():
    try:
        with open("chosen_channels.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    
def save_chosen_channels(chosen_channels):
    with open("chosen_channels.json", "w") as f:
        json.dump(chosen_channels, f)

# Load if able
chosen_channels = load_chosen_channels()

# Maximum number of tokens to keep in conversation history (see https://openai.com/pricing for details)
token_limits = {
    'gpt-3.5-turbo': 3500,
    'gpt-4': 7500,
    'gpt-4-vision-preview': 8000,
}

# OpenAI api key
apikey = "ollama"
# Discord stuff
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

client = MyClient(intents=intents)
client.run("DISCORD-BOT-TOKEN")

import os
import discord
import json

class MyClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Load count from file, or start at 0
        try:
            with open('count.json', 'r') as f:
                self.count = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.count = {'ner': 0, 'na': 0}

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    async def on_message(self, message):
        if message.author == self.user:
            return

        if 'ner' in message.content:
            self.count['ner'] += 1
            await message.channel.send(f'Total N-word count: {self.count["ner"]}')

        if 'na' in message.content:
            self.count['na'] += 1
            await message.channel.send(f'Total N-word count: {self.count["ner"] + self.count["na"]}')

        if message.content == '!ncount':
            await message.channel.send(f'Total N-word count: {self.count["ner"] + self.count["na"]}')

        # Save count to file
        with open('count.json', 'w') as f:
            json.dump(self.count, f)

intents = discord.Intents.default()
intents.message_content = True

client = MyClient(intents=intents)
TOKEN = 'DISCORD-TOKEN'
client.run(TOKEN)

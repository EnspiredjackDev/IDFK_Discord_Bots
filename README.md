# IDFK_Discord_Bots
All the bots running on the IDFK discord server that I've made  
---
These bots are very basic and just me messing about.  

## GPT bot  
This bot gets every message from the server and replies to it, adding the conversation to the memory, configure how long you want the memory by changing the `MAX_CONVERSATION_LENGTH` to something else. Conversation does not include the system message, it will not be deleted. This is the single message respose version, it will send a message once openai's API has responded.  

`!helpgpt` for help menu  

## GPT bot stream  
This is the same as above but it will send a message and then continuously edit that message until the response is fully added.  
Instead of the max conversation length variable, there is now token limits to all of the models, you can set maximum tokens allowed in a conversation, and it will always fit into the models context window, and if it doesn't, an older message gets popped out of the context.  
  
Remember to add the `OPENAI-API-KEY` and `DISCORD-BOT-TOKEN` for the bot to function.  
Use `!setchannel` to set the channel for the AI to talk in otherwise it will not be able to talk.

## n-word bot  
Just counts how many times the n-word is said, good for toxic servers i guess. (had to remove the actual words, just add them back)  

## AI image bot  
Uses DALL-E 3 image api to generate images when someone says !generateimage [prompt] (if thats too long, just change it in the script) 

## Prerequisits
Make sure you have openai, tiktoken and discord installed via pip for AI related bots, however discord is still required for normal ones.
`pip install openai tiktoken discord`  

When creating and inviting the bot, make sure you select 'bot' and 'message.read' and in the 'Bot Permissions' area, select 'read messages/view channels' and 'send messages'  

Get a API token at [OpenaAI](https://platform.openai.com)  
Get discord bot + token at [Discord](https://discord.com/developers/applications)

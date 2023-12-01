# IDFK_Discord_Bots
All the bots running on the IDFK discord server that ive made  
---
These bots are very basic and just me messing about.  

## GPT bot  
This bot gets every message from the server and replies to it, adding the conversation to the memory, configure how long you want the memory by changing the `MAX_CONVERSATION_LENGTH` to something else. Conversation does not include the system message, it will not be deleted. This is the single message respose version, it will send a message once openai's API has responded. (Not updated to latest version of OAI lib)  

## GPT bot stream  
This is the same as above but it will send a message and then continuously edit that message until the response is fully added.  
  
Remember to add the `OPENAI-API-KEY` and `DISCORD-BOT-TOKEN` for the bot to function.  
Use `!setchannel` to set the channel for the AI to talk in otherwise it will not be able to talk.

## n-word bot  
Just counts how many times the n-word is said, good for toxic servers i guess. (had to remove the actual words, just add them back)  

## AI image bot  
Uses DALL-E 2 image api to generate images when someone says !generateimage prompt (changable) (Not updated to latest version of OAI lib) 

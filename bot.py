import os
import json
import random
import urllib.parse
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GROK_API_KEY = os.environ["GROK_API_KEY"]

CHAT_API_URL = "https://api.x.ai/v1/chat/completions"
IMAGE_API_URL = "https://image.pollinations.ai/prompt/{prompt}"
PERSONA_FILE = os.path.join(os.path.dirname(__file__), "persona.json")

DEFAULT_PERSONA = {
    "name": "AIるな",
    "gender": "女の子",
    "personality": "明るくて親切、少しおっちょこちょい",
    "speaking_style": "友達に話しかけるような口調。語尾に「だよ」「だね」「かな？」を使う。",
}


def load_persona() -> dict:
    if os.path.exists(PERSONA_FILE):
        with open(PERSONA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_PERSONA.copy()


def save_persona(persona: dict):
    with open(PERSONA_FILE, "w", encoding="utf-8") as f:
        json.dump(persona, f, ensure_ascii=False, indent=2)


def build_system_prompt(persona: dict) -> str:
    return (
        f"あなたの名前は「{persona['name']}」です。\n"
        f"性別: {persona['gender']}\n"
        f"性格: {persona['personality']}\n"
        f"話し方: {persona['speaking_style']}\n"
        f"このキャラクターを維持して、日本語で自然に会話してください。"
        f"自分のキャラクター設定を直接口にしたり、AIだと強調しすぎず、自然に振る舞ってください。"
    )


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

conversation_histories: dict[int, list[dict]] = {}
persona = load_persona()


async def chat_with_ai(user_id: int, user_message: str) -> str:
    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    system = build_system_prompt(persona)
    messages = [{"role": "system", "content": system}]
    messages += conversation_histories[user_id]
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": "grok-3-mini",
        "messages": messages,
    }

    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(CHAT_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json()
            reply = data["choices"][0]["message"]["content"]

    conversation_histories[user_id].append({"role": "user", "content": user_message})
    conversation_histories[user_id].append({"role": "assistant", "content": reply})

    if len(conversation_histories[user_id]) > 20:
        conversation_histories[user_id] = conversation_histories[user_id][-20:]

    return reply


async def generate_image_url(prompt: str) -> str:
    encoded = urllib.parse.quote(prompt)
    seed = random.randint(1, 99999)
    url = IMAGE_API_URL.format(prompt=encoded) + f"?width=1024&height=1024&nologo=true&seed={seed}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            final_url = str(resp.url)

    return final_url


@bot.event
async def on_ready():
    print(f"Bot起動完了: {bot.user} (ID: {bot.user.id})")
    for guild in bot.guilds:
        try:
            tree.copy_global_to(guild=guild)
            synced = await tree.sync(guild=guild)
            print(f"[{guild.name}] コマンド同期完了: {len(synced)}個")
        except Exception as e:
            print(f"[{guild.name}] コマンド同期エラー: {e}")


@bot.event
async def on_guild_join(guild: discord.Guild):
    try:
        tree.copy_global_to(guild=guild)
        synced = await tree.sync(guild=guild)
        print(f"新サーバー [{guild.name}] に参加 → コマンド即時同期: {len(synced)}個")
    except Exception as e:
        print(f"新サーバー [{guild.name}] コマンド同期エラー: {e}")


class PersonaModal(discord.ui.Modal, title="Botのキャラクター設定"):
    bot_name = discord.ui.TextInput(
        label="名前",
        placeholder="例：るな、ハル、アリス",
        default=DEFAULT_PERSONA["name"],
        max_length=30,
    )
    gender = discord.ui.TextInput(
        label="性別・属性",
        placeholder="例：女の子、男の子、性別不明の妖精",
        default=DEFAULT_PERSONA["gender"],
        max_length=50,
    )
    personality = discord.ui.TextInput(
        label="性格",
        placeholder="例：元気でちょっとドジ、クールで無口、天然でマイペース",
        default=DEFAULT_PERSONA["personality"],
        max_length=200,
        style=discord.TextStyle.paragraph,
    )
    speaking_style = discord.ui.TextInput(
        label="話し方・口調",
        placeholder="例：語尾に「だよ」「～かな？」を使う。タメ口で話す。",
        default=DEFAULT_PERSONA["speaking_style"],
        max_length=300,
        style=discord.TextStyle.paragraph,
    )

    async def on_submit(self, interaction: discord.Interaction):
        global persona
        persona = {
            "name": self.bot_name.value,
            "gender": self.gender.value,
            "personality": self.personality.value,
            "speaking_style": self.speaking_style.value,
        }
        save_persona(persona)
        conversation_histories.clear()

        embed = discord.Embed(
            title="キャラクター設定を更新しました！",
            color=discord.Color.purple()
        )
        embed.add_field(name="名前", value=persona["name"], inline=True)
        embed.add_field(name="性別・属性", value=persona["gender"], inline=True)
        embed.add_field(name="性格", value=persona["personality"], inline=False)
        embed.add_field(name="話し方", value=persona["speaking_style"], inline=False)
        embed.set_footer(text="会話履歴はリセットされました")
        await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="persona", description="Botの性格・話し方などキャラクターを設定します（管理者向け）")
@app_commands.default_permissions(administrator=True)
async def persona_command(interaction: discord.Interaction):
    modal = PersonaModal()
    modal.bot_name.default = persona["name"]
    modal.gender.default = persona["gender"]
    modal.personality.default = persona["personality"]
    modal.speaking_style.default = persona["speaking_style"]
    await interaction.response.send_modal(modal)


@tree.command(name="persona-show", description="現在のBotのキャラクター設定を確認します")
async def persona_show_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title=f"現在のキャラクター設定",
        color=discord.Color.purple()
    )
    embed.add_field(name="名前", value=persona["name"], inline=True)
    embed.add_field(name="性別・属性", value=persona["gender"], inline=True)
    embed.add_field(name="性格", value=persona["personality"], inline=False)
    embed.add_field(name="話し方", value=persona["speaking_style"], inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="t", description="AIと会話します（完全無料）")
@app_commands.describe(message="AIへのメッセージ")
async def talk_command(interaction: discord.Interaction, message: str):
    await interaction.response.defer(thinking=True)
    try:
        reply = await chat_with_ai(interaction.user.id, message)
        embed = discord.Embed(description=reply, color=discord.Color.blue())
        embed.set_author(name=persona["name"], icon_url=bot.user.display_avatar.url)
        embed.set_footer(text=f"{interaction.user.display_name}との会話")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"エラーが発生しました: {str(e)}")


@tree.command(name="c", description="AIで画像を生成します（完全無料）")
@app_commands.describe(prompt="生成したい画像の説明（例：夕暮れの富士山）")
async def create_image_command(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer(thinking=True)
    try:
        image_url = await generate_image_url(prompt)
        embed = discord.Embed(
            title="画像生成完了",
            description=f"**プロンプト:** {prompt}",
            color=discord.Color.green()
        )
        embed.set_image(url=image_url)
        embed.set_footer(text=f"{interaction.user.display_name}がリクエスト • Powered by Pollinations.ai")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"画像生成エラー: {str(e)}")


@tree.command(name="reset", description="AIとの会話履歴をリセットします")
async def reset_command(interaction: discord.Interaction):
    conversation_histories.pop(interaction.user.id, None)
    await interaction.response.send_message("会話履歴をリセットしました！新しい話題から始められます。", ephemeral=True)


question_mode_users: set[int] = set()


@tree.command(name="q", description="質問受付モードの切り替え（ONでメンションなしでも回答）")
async def question_mode_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id in question_mode_users:
        question_mode_users.discard(user_id)
        await interaction.response.send_message("質問受付モードを**OFF**にしました。", ephemeral=True)
    else:
        question_mode_users.add(user_id)
        await interaction.response.send_message("質問受付モードを**ON**にしました。次のメッセージから自動で回答します。", ephemeral=True)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    is_mentioned = bot.user in message.mentions
    is_in_question_mode = message.author.id in question_mode_users

    if not is_mentioned and not is_in_question_mode:
        return

    content = message.content
    for mention in message.mentions:
        content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    content = content.strip()

    if not content:
        await message.reply("何かご質問はありますか？")
        return

    async with message.channel.typing():
        try:
            reply = await chat_with_ai(message.author.id, content)

            if len(reply) > 2000:
                chunks = [reply[i:i+1900] for i in range(0, len(reply), 1900)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await message.reply(chunk)
                    else:
                        await message.channel.send(chunk)
            else:
                await message.reply(reply)

        except Exception as e:
            await message.reply(f"エラーが発生しました: {str(e)}")


bot.run(DISCORD_BOT_TOKEN)

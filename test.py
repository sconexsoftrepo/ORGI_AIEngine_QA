from pydub import AudioSegment

final = AudioSegment.empty()

for i in range(1, 10):
    final += AudioSegment.from_mp3(f"{i}.mp3")

final.export("final_quiz_intro.mp3", format="mp3")

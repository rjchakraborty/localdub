"""Exercise the actual PCM pipe contract used by Whisper's audio loader."""
import subprocess
import numpy as np
import soundfile as sf


def test_whisper_raw_pcm_pipe(tmp_path):
    source=tmp_path/'voice.wav'
    sf.write(source,np.sin(np.arange(24000)*2*np.pi*220/24000)*.1,24000)
    output=subprocess.check_output(['ffmpeg','-nostdin','-threads','0','-i',str(source),
        '-f','s16le','-ac','1','-acodec','pcm_s16le','-ar','16000','-'],stderr=subprocess.PIPE)
    assert len(output)==32000
    assert np.max(np.abs(np.frombuffer(output,dtype=np.int16)))>100

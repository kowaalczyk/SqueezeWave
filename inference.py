# We retain the copyright notice by NVIDIA from the original code. However, we
# we reserve our rights on the modifications based on the original code.
#
# *****************************************************************************
#  Copyright (c) 2018, NVIDIA CORPORATION.  All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are met:
#      * Redistributions of source code must retain the above copyright
#        notice, this list of conditions and the following disclaimer.
#      * Redistributions in binary form must reproduce the above copyright
#        notice, this list of conditions and the following disclaimer in the
#        documentation and/or other materials provided with the distribution.
#      * Neither the name of the NVIDIA CORPORATION nor the
#        names of its contributors may be used to endorse or promote products
#        derived from this software without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
#  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
#  ARE DISCLAIMED. IN NO EVENT SHALL NVIDIA CORPORATION BE LIABLE FOR ANY
#  DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
#  (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
#  LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
#  ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
#  SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# *****************************************************************************
import os
from scipy.io.wavfile import write
import torch
from mel2samp import files_to_list, MAX_WAV_VALUE
from denoiser import Denoiser
from device import get_default_device


def main(
        mel_files, 
        squeezewave_path, 
        sigma, 
        output_dir, 
        sampling_rate, 
        is_fp16,
        denoiser_strength,
        device
):
    mel_files = files_to_list(mel_files)
    squeezewave = torch.load(squeezewave_path, map_location=device)['model']
    squeezewave.device = device  # hack for loading model trained on gpu to cpu
    squeezewave = squeezewave.remove_weightnorm(squeezewave)
    squeezewave.to(device=device).eval()
    if is_fp16:
        from apex import amp
        squeezewave, _ = amp.initialize(squeezewave, [], opt_level="O3")

    if denoiser_strength > 0:
        denoiser = Denoiser(squeezewave).to(device=device)

    for i, file_path in enumerate(mel_files):
        file_name = os.path.splitext(os.path.basename(file_path))[0]
        mel = torch.load(file_path)
        if len(mel.shape) > 2:
            mel = mel.squeeze()
            print(f"squeezed to {mel.shape}")
        assert len(mel.shape) == 2
        mel = torch.autograd.Variable(mel.to(device=device))
        mel = torch.unsqueeze(mel, 0)
        mel = mel.half() if is_fp16 else mel
        with torch.no_grad():
            audio = squeezewave.infer(mel, sigma=sigma).float()
            if denoiser_strength > 0:
                audio = denoiser(audio, denoiser_strength)
            audio = audio * MAX_WAV_VALUE
        audio = audio.squeeze()
        audio = audio.cpu().numpy()
        audio = audio.astype('int16')
        audio_path = os.path.join(
            output_dir, "{}_synthesis.wav".format(file_name))
        write(audio_path, sampling_rate, audio)
        print(audio_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-f', "--filelist_path", required=True)
    parser.add_argument('-w', '--squeezewave_path',
                        help='Path to squeezewave decoder checkpoint with model')
    parser.add_argument('-o', "--output_dir", required=True)
    parser.add_argument("-s", "--sigma", default=1.0, type=float)
    parser.add_argument("--sampling_rate", default=22050, type=int)
    parser.add_argument("--is_fp16", action="store_true")
    parser.add_argument("-d", "--denoiser_strength", default=0.0, type=float,
                        help='Removes model bias. Start with 0.1 and adjust')
    parser.add_argument("-D", "--device", default=get_default_device())

    args = parser.parse_args()

    main(args.filelist_path, args.squeezewave_path, args.sigma, args.output_dir,
         args.sampling_rate, args.is_fp16, args.denoiser_strength, args.device)

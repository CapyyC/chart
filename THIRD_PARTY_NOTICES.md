# Third-party notices

## Models (bundled in builds, downloaded on first use when running from source)

### ADTOF Frame_RNN: drum transcription
* Files: `adtof_frame_rnn.onnx` from <https://huggingface.co/thebluescreen/adtof-drums-onnx>
  (revision d0e809bb), an ONNX conversion of checkpoint `Frame_RNN_adtofAll_0` of
  <https://github.com/MZehren/ADTOF>.
* Authors: Mickaël Zehren, Marco Alunno, Paolo Bientinesi.
  "High-Quality and Reproducible Automatic Drum Transcription from Crowdsourced Data",
  Signals 2023, 4(4), 768-787; "ADTOF: A large dataset of non-synthetic music for automatic drum
  transcription", ISMIR 2021.
* Licence: Creative Commons Attribution-NonCommercial-ShareAlike 4.0
  (<https://creativecommons.org/licenses/by-nc-sa/4.0/>). The model is used unmodified;
  distributions of AutoDrums that include it are for non-commercial use only.

### Beat This!: beat and downbeat tracking
* Files: `beat_this.onnx` from <https://huggingface.co/thebluescreen/beat-this-onnx>
  (revision 92842057), an ONNX conversion of the `final0` checkpoint of
  <https://github.com/CPJKU/beat_this>.
* Authors: Francesco Foscarin, Jan Schlüter, Gerhard Widmer. "Beat this! Accurate beat tracking
  without DBN postprocessing", ISMIR 2024.
* Licence: MIT. Copyright (c) 2024 Institute of Computational Perception, JKU Linz, Austria.

### HT-Demucs FT (drums specialist): source separation
* Files: `htdemucs_ft_drums_fp16weights.onnx` from
  <https://huggingface.co/StemSplitio/htdemucs-ft-drums-onnx> (revision 55f929d3), an ONNX export
  of sub-model 0 of `htdemucs_ft` from <https://github.com/facebookresearch/demucs>.
* Authors: Simon Rouard, Francisco Massa, Alexandre Défossez. "Hybrid Transformers for Music Source
  Separation", ICASSP 2023.
* Licence: MIT.

## Software bundled in the Windows build

* yt-dlp: The Unlicense. <https://github.com/yt-dlp/yt-dlp>
* yt-dlp-ejs: The Unlicense / MIT. <https://github.com/yt-dlp/ejs>
* FFmpeg (LGPL build by BtbN): GNU LGPL 2.1+. <https://ffmpeg.org>
* Deno: MIT. <https://deno.com>
* Qt 6 / PySide6: GNU LGPL 3. <https://www.qt.io>
* ONNX Runtime: MIT. <https://onnxruntime.ai>
* NumPy, SciPy: BSD.

## Evaluation data (not distributed)

`tools/eval_mdb.py` and `tools/eval_lanes.py` were used with MDB Drums++
(<https://huggingface.co/datasets/xavriley/MDBDrumsPlusPlus>, CC BY-NC-SA 4.0), and
`tools/eval_slakh.py` with Slakh2100 test tracks.

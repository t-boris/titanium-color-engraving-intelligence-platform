# Model files

## face_detection_yunet_2023mar.onnx

YuNet face detector used by `titanium_platform.faces` through OpenCV's `cv2.FaceDetectorYN` (REQ-033, DEC-074).

- Source: OpenCV Zoo, `models/face_detection_yunet/face_detection_yunet_2023mar.onnx`,
  https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
  (downloaded 2026-10-18 from https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx,
  last changed upstream in commit f12e12798e8314f7c074a6656816c048dcc95b7a, "update yunet to v2 (#151)", 2023-06-06)
- Size: 232589 bytes
- SHA-256: `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`
- Licence: MIT, Copyright (c) 2020 Shiqi Yu, as stated by the model's own directory in OpenCV Zoo ("All files in this
  directory are licensed under MIT License"); the full text is in `LICENSE-face_detection_yunet` beside the model.
  OpenCV Zoo as a whole is Apache-2.0, but it refers to the licence of each model, and this model's is MIT.

## selfie_multiclass_256x256.onnx

MediaPipe multiclass selfie segmentation (background, hair, body skin, face skin, clothes, others) used by `titanium_platform.people`
through OpenCV's `cv2.dnn.readNetFromONNX` to find the parts of a photo for the photo engraving's "Попросить AI" (REQ-062, DEC-105). OpenCV 5's
TFLite reader cannot run the original (`TRANSPOSE_CONV` is not supported), so the model was converted once to ONNX; no new library is
needed at run time.

- Source: https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite
  (downloaded 2026-10-22; 16371837 bytes; SHA-256 `c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0`), listed in the
  MediaPipe Image Segmenter guide, https://developers.google.com/edge/mediapipe/solutions/vision/image_segmenter
- Conversion: `python -m tf2onnx.convert --tflite selfie_multiclass_256x256.tflite --output selfie_multiclass_256x256.onnx --opset 13`
  (tf2onnx 1.17.0, tensorflow 2.21.0, in a throwaway environment). On a photo of two people the ONNX output (onnxruntime 1.31.0) differs
  from the TFLite interpreter's by at most 6e-5 and gives the same class for 100 % of pixels; OpenCV 5.0.0 runs it in about 0.06 s.
- Input: RGB 256 x 256, values 0..1, NHWC. Output: 256 x 256 x 6 scores, the class of a pixel is the largest.
- Size: 16454477 bytes
- SHA-256: `8567a192957398d114cd567e8c9d54519183305221cb838c8824ab09406dbf03`
- Licence: Apache License 2.0, as the model card states ("LICENSED UNDER Apache License, Version 2.0", Model Card Multiclass Segmentation,
  Google, May 10, 2023, https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Multiclass%20Segmentation.pdf); the full text is in
  `LICENSE-selfie_multiclass`. The card puts surveillance and identity recognition out of scope; here the model only finds parts of a picture
  so that each can be given its own tones.

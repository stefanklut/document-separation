from functools import lru_cache

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision
from transformers import RobertaConfig, RobertaModel, RobertaTokenizer


class LazyLinearBlock(nn.Module):
    def __init__(self, out_features, dropout=0.0):
        super(LazyLinearBlock, self).__init__()
        self.fc = nn.LazyLinear(out_features)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        x = self.fc(x)
        x = F.relu(x)
        x = self.dropout(x)
        return x


class TextEncoder(nn.Module):
    def __init__(self, channels=512, merge_to_batch=True):
        super(TextEncoder, self).__init__()
        self.merge_to_batch = merge_to_batch

        self.tokenizer = RobertaTokenizer.from_pretrained("pdelobelle/robbert-v2-dutch-base")
        self.roberta = RobertaModel.from_pretrained("pdelobelle/robbert-v2-dutch-base", add_pooling_layer=False)

        self.fc = nn.Sequential(
            LazyLinearBlock(512),
            nn.Linear(512, channels),
        )

    @property
    @lru_cache
    def device(self):
        return next(self.parameters()).device

    def encode_text(self, text: list[str]):
        # Tokenize the text
        encoded_text = self.tokenizer(text, padding=True, truncation=True, return_tensors="pt")  # (B, S)
        encoded_text = {key: tensor.to(self.device) for key, tensor in encoded_text.items()}

        # Encode the text
        encoded_text = self.roberta(**encoded_text).last_hidden_state  # (B, S, 768)
        encoded_text = encoded_text[:, 0]  # (B, 768)
        encoded_text = self.fc(encoded_text)  # (B, channels)

        return encoded_text

    def forward(self, x: list[str]):
        return self.encode_text(x)


class TextFeaturesArray(nn.Module):
    def __init__(
        self,
        channels,
        height,
        width,
        old_height=None,
        old_width=None,
        text_encoder=TextEncoder(merge_to_batch=True),
        mode="baseline",
    ):
        super(TextFeaturesArray, self).__init__()
        self.text_encoder = text_encoder
        self.channels = channels
        self.height = height
        self.width = width
        self.old_height = old_height
        self.old_width = old_width
        self.mode = mode

    def forward(self, x: list[list[dict]], old_height=None, old_width=None):
        B = len(x)
        N = len(x[0])
        sum_array = torch.zeros(
            B,
            N,
            self.channels,
            self.height,
            self.width,
            dtype=torch.float32,
            device=self.text_encoder.device,
        )
        sum_mask = torch.zeros(
            B,
            N,
            1,
            self.height,
            self.width,
            dtype=torch.float32,
            device=self.text_encoder.device,
        )
        if old_height is not None:
            self.old_height = old_height
        if old_width is not None:
            self.old_width = old_width

        scale = np.array([self.height / self.old_height, self.width / self.old_width])
        for i, batch in enumerate(x):
            for j, document in enumerate(batch):
                for text_line in document.values():
                    if text_line["text"] == "":
                        continue
                    encoded_text = self.text_encoder([text_line["text"]])

                    # Add the text to the array
                    if self.mode == "baseline":
                        baseline = text_line["baseline"]
                        if baseline is None:
                            continue
                        baseline = (baseline * scale).round().astype(int)
                        mask = np.zeros((self.height, self.width))
                        mask = cv2.polylines(mask, [baseline], False, 1, 1)
                        mask = torch.from_numpy(mask).to(dtype=torch.bool, device=self.text_encoder.device)[:, :]
                    elif self.mode == "bbox":
                        bbox = text_line["bbox"]
                        if bbox is None:
                            continue
                        bbox = (bbox * scale).round().astype(int)
                        mask = torch.zeros(self.height, self.width, dtype=torch.bool)
                        mask[bbox[1] : bbox[3], bbox[0] : bbox[2]] = 1
                    else:
                        raise ValueError(f"Unknown mode: {self.mode}")

                    sum_array[i, j, :, mask] = sum_array[i, j, :, mask] + encoded_text[..., None]
                    sum_mask[i, j] = sum_mask[i, j] + mask

            avg_array = sum_array / torch.maximum(sum_mask, torch.ones_like(sum_mask))

        return avg_array


if __name__ == "__main__":
    text_features_array = TextFeaturesArray(channels=16, height=100, width=100)
    x = [
        [
            {
                "text": "This is the first test line",
                "baseline": torch.tensor([[10, 10], [20, 20]]),
                "bbox": torch.tensor([10, 10, 20, 20]),
            },
            {
                "text": "This is the second test line",
                "baseline": torch.tensor([[40, 40], [20, 20]]),
                "bbox": torch.tensor([40, 40, 20, 20]),
            },
        ]
    ]
    output = text_features_array(x)
    print([parameter.grad for parameter in text_features_array.text_encoder.roberta.parameters()])
    loss = output.sum()
    loss.backward()

    print([parameter.grad for parameter in text_features_array.text_encoder.roberta.parameters()])
    # print(torch.unique(output))

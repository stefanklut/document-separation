import functools
import sys
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import torch
from torch.utils.data import Dataset
from torchvision import transforms

sys.path.append(str(Path(__file__).resolve().parent.joinpath("..")))
from page_xml.xmlPAGE import PageData
from utils.image_utils import load_image_array_from_path
from utils.path_utils import check_path_accessible, image_path_to_xml_path


class DocumentSeparationDataset(Dataset):
    def __init__(
        self,
        image_paths: Sequence[Sequence[Path]],
        target: Optional[Sequence[Sequence[int]]] = None,
        number_of_images=3,
        randomize_document_order=False,
        transform=None,
    ):

        self.idx_to_idcs = {}
        idx = 0
        self.doc_lenghts = []

        for i, doc_i in enumerate(image_paths):
            self.doc_lenghts.append(len(doc_i))
            for j, path_i in enumerate(doc_i):
                check_path_accessible(path_i)
                xml_path_i = image_path_to_xml_path(path_i)
                self.idx_to_idcs[idx] = (i, j)
                idx += 1

        self.len = sum(self.doc_lenghts)
        self.image_paths = image_paths
        if target is not None:
            self.target = target
        else:
            # If no target is provided, assume that the first image in the document is the target
            self.target = []
            for i in range(len(image_paths)):
                self.target.append([])
                for j in range(len(image_paths[i])):
                    if j == 0:
                        self.target[i].append(1)
                    self.target[i].append(0)

        assert number_of_images > 0, "Number of images must be greater than 0"
        self.number_of_images = number_of_images
        self.randomize_document_order = randomize_document_order
        self.transform = transform

    def __len__(self):
        return self.len

    @functools.lru_cache(maxsize=128)
    def get_image(self, i, j):
        image_path = self.image_paths[i][j]
        data = load_image_array_from_path(image_path)
        if data is None:
            raise ValueError(f"Could not load image from path {image_path}")
        image = data["image"]
        return image

    @functools.lru_cache(maxsize=128)
    def get_text(self, i, j):
        xml_path = image_path_to_xml_path(self.image_paths[i][j])
        page_data = PageData(xml_path)
        page_data.parse()
        text = page_data.get_transcription()
        total_text = ""
        for _, text_line in text.items():
            # If line ends with - then add it to the next line, otherwise add a space
            text_line = text_line.strip()
            if len(text_line) > 0:
                if text_line[-1] == "-":
                    text_line = text_line[:-1]
                else:
                    text_line += " "

            total_text += text_line
        return total_text

    def start_of_document(self, i, j):
        return j == 0

    def end_of_document(self, i, j):
        return j == self.doc_lenghts[i] - 1

    def is_first_document(self, i, j):
        return i == 0 and j == 0

    def is_last_document(self, i, j):
        return i == len(self.image_paths) - 1 and j == self.doc_lenghts[i] - 1

    def get_next_scan(self, i, j):
        if self.end_of_document(i, j):
            if self.is_last_document(i, j):
                return 0, 0
            return i + 1, 0
        else:
            return i, j + 1

    def get_previous_scan(self, i, j):
        if self.start_of_document(i, j):
            if self.is_first_document(i, j):
                return len(self.image_paths) - 1, self.doc_lenghts[-1] - 1
            return i - 1, self.doc_lenghts[i - 1] - 1
        else:
            return i, j - 1

    # https://stackoverflow.com/a/64015315
    @staticmethod
    def random_choice_except(high: int, excluding: int, size=None, replace=True):
        assert isinstance(high, int), "high must be an integer"
        assert excluding < high, "excluding value must be less than high"
        # generate random values in the range [0, high-1)
        choices = np.random.choice(high - 1, size, replace=replace)
        # shift values to avoid the excluded number
        return choices + (choices >= excluding)

    def get_random_previous_scan(self, i, j):
        if self.start_of_document(i, j):
            random_i = self.random_choice_except(len(self.image_paths), i)
            return random_i, self.doc_lenghts[random_i] - 1
        else:
            return i, j - 1

    def get_random_next_scan(self, i, j):
        if self.end_of_document(i, j):
            random_i = self.random_choice_except(len(self.image_paths), i)
            return random_i, 0
        else:
            return i, j + 1

    def __getitem__(self, idx):
        steps_back = self.number_of_images // 2
        steps_forward = self.number_of_images - 1 - steps_back

        if self.randomize_document_order:
            idcs = []
            i, j = self.idx_to_idcs[idx]

            # Steps back
            prev_i, prev_j = i, j
            for _ in range(steps_back):
                prev_i, prev_j = self.get_random_previous_scan(prev_i, prev_j)
                idcs.append((prev_i, prev_j))

            # Current
            idcs.append((i, j))

            # Steps forward
            next_i, next_j = i, j
            for _ in range(steps_forward):
                next_i, next_j = self.get_random_next_scan(next_i, next_j)
                idcs.append((next_i, next_j))
        else:
            idcs = []
            i, j = self.idx_to_idcs[idx]

            # Steps back
            prev_i, prev_j = i, j
            for _ in range(steps_back):
                prev_i, prev_j = self.get_previous_scan(prev_i, prev_j)
                idcs.append((prev_i, prev_j))

            # Current
            idcs.append((i, j))

            # Steps forward
            next_i, next_j = i, j
            for _ in range(steps_forward):
                next_i, next_j = self.get_next_scan(next_i, next_j)
                idcs.append((next_i, next_j))

        targets = []
        images = []
        texts = []
        shapes = []
        targets = []
        for i, j in idcs:
            target = self.target[i][j]
            image = self.get_image(i, j)
            shape = image.shape[:2]
            text = self.get_text(i, j)

            if self.transform:
                image = self.transform(image)
            else:
                image = torch.tensor(image).permute(2, 0, 1)

            targets.append(target)
            images.append(image)
            shapes.append(shape)
            texts.append(text)

        # Pad to the same size
        max_shape = max([img.size()[-1] for img in images])
        for i in range(len(images)):
            images[i] = torch.nn.functional.pad(images[i], (0, max_shape - images[i].size()[-1]), value=0)

        return {"image": images, "shape": shapes, "text": texts, "targets": targets}


def collate_fn(batch):
    images = []
    shapes = []
    texts = []
    targets = []
    for item in batch:
        # Pad to the same size
        max_shape = max([img.size()[-1] for img in item["image"]])
        for i in range(len(item["image"])):
            item["image"][i] = torch.nn.functional.pad(item["image"][i], (0, max_shape - item["image"][i].size()[-1]), value=0)
        images.append(torch.stack(item["image"]))

        shapes.append(item["shape"])
        texts.append(item["text"])
        targets.append(item["targets"])

    images = torch.stack(images)
    shapes = torch.tensor(shapes)
    targets = torch.tensor(targets)

    return {"images": images, "shapes": shapes, "texts": texts, "targets": targets}


if __name__ == "__main__":
    test_image_paths = [
        [
            Path("/home/stefan/Downloads/ushmm_test/113I/NL-HaNA_2.09.09_113I_0001.jpg"),
            Path("/home/stefan/Downloads/ushmm_test/113I/NL-HaNA_2.09.09_113I_0002.jpg"),
        ],
        [Path("/home/stefan/Downloads/ushmm_test/113I/NL-HaNA_2.09.09_113I_0003.jpg")],
        [Path("/home/stefan/Downloads/ushmm_test/113I/NL-HaNA_2.09.09_113I_0004.jpg")],
        [
            Path("/home/stefan/Downloads/ushmm_test/113I/NL-HaNA_2.09.09_113I_0005.jpg"),
            Path("/home/stefan/Downloads/ushmm_test/113I/NL-HaNA_2.09.09_113I_0006.jpg"),
            Path("/home/stefan/Downloads/ushmm_test/113I/NL-HaNA_2.09.09_113I_0007.jpg"),
        ],
        [Path("/home/stefan/Downloads/ushmm_test/113I/NL-HaNA_2.09.09_113I_0008.jpg")],
    ]
    transform = transforms.Compose([transforms.ToTensor(), transforms.Resize((224, 224))])
    dataset = DocumentSeparationDataset(test_image_paths, transform=transform)
    import torch.utils.data

    dataloader = torch.utils.data.DataLoader(dataset, batch_size=5, shuffle=True, collate_fn=collate_fn)
    item = next(iter(dataloader))
    print(item["images"].size())
    print(item["shapes"].size())
    print(item["targets"].size())
    # Text size is not fixed, so it is a list of lists
    print(len(item["texts"]), len(item["texts"][0]))

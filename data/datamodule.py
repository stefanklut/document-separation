import itertools
import random
import sys
from pathlib import Path
from typing import Optional, Sequence

import pytorch_lightning as pl
from natsort import natsorted
from torch.utils.data import DataLoader

sys.path.append(str(Path(__file__).resolve().parent.joinpath("..")))
from data.convert_xlsx import link_with_paths, read_xlsx
from data.dataloader import collate_fn
from data.dataset import DocumentSeparationDataset


def split_training_paths(
    training_paths: Sequence[Path], split_ratio: float = 0.8, seed: int = 42
) -> tuple[Sequence[Path], Sequence[Path]]:
    """
    Split training paths into training and validation paths while keeping files from the same folder together. And keeping the order of the files.

    Args:
        training_paths (Sequence[Path]): Paths to the training files
        split_ratio (float): Ratio to split the training paths. Default is 0.8

    Returns:
        Tuple[Sequence[Path], Sequence[Path]]: Tuple of training and validation paths
    """
    training_paths = natsorted(training_paths)
    # Group the paths by parent folder
    grouped_training_paths = [list(group) for _, group in itertools.groupby(training_paths, key=lambda x: x.parent)]

    # Shuffle the groups
    random.seed(seed)
    random.shuffle(grouped_training_paths)

    # Split the groups
    split_idx = int(len(grouped_training_paths) * split_ratio)
    split_training_paths = list(itertools.chain.from_iterable(grouped_training_paths[:split_idx]))
    split_val_paths = list(itertools.chain.from_iterable(grouped_training_paths[split_idx:]))

    return split_training_paths, split_val_paths


class DocumentSeparationModule(pl.LightningDataModule):
    def __init__(
        self,
        training_paths: Sequence[Path],
        val_paths: Optional[Sequence[Path]],
        xlsx_file: Path,
        number_of_images: int = 3,
    ):
        super().__init__()
        self.training_paths = training_paths

        if val_paths is None:
            # split training paths 80/20
            self.training_paths, self.val_paths = split_training_paths(self.training_paths, split_ratio=0.8, seed=101)
        else:
            self.val_paths = val_paths

        self.xlsx_file = xlsx_file
        self.number_of_images = number_of_images

    def prepare_data(self):
        # download, split, etc...
        pass

    def setup(self, stage=None):
        xlsx_data = read_xlsx(self.xlsx_file)
        training_paths = link_with_paths(xlsx_data, self.training_paths)
        val_paths = link_with_paths(xlsx_data, self.val_paths)

        if stage == "fit" or stage is None:
            self.train_dataset = DocumentSeparationDataset(training_paths, number_of_images=self.number_of_images)
            self.val_dataset = DocumentSeparationDataset(val_paths, number_of_images=self.number_of_images)

    def train_dataloader(self):
        return DataLoader(self.train_dataset, collate_fn=collate_fn)

    def val_dataloader(self):
        return DataLoader(self.val_dataset, collate_fn=collate_fn)
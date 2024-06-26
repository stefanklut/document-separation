import pytorch_lightning as pl
import torch
from pytorch_lightning.loggers import TensorBoardLogger
from torch.nn import functional as F
from torch.utils.data import DataLoader, random_split
from torchmetrics import Accuracy
from torchvision import datasets, transforms


class ClassificationModel(pl.LightningModule):
    def __init__(self, model, learning_rate=1e-4):
        super(ClassificationModel, self).__init__()
        self.model = model
        self.learning_rate = learning_rate
        self.train_accuracy = Accuracy(task="multiclass", num_classes=2)
        self.val_accuracy = Accuracy(task="multiclass", num_classes=2)
        self.test_accuracy = Accuracy(task="multiclass", num_classes=2)

        self.weight = torch.tensor([1, 3], dtype=torch.float)

    def forward(self, x):
        return self.model(x)

    def split_input(self, batch):
        y = batch["targets"]
        y = y.type(torch.int64)
        del batch["targets"]
        x = batch
        return x, y

    def get_middle_scan(self, y, N):
        i = N // 2
        return y[:, i]

    def training_step(self, batch, batch_idx):
        x, y = self.split_input(batch)
        B = y.shape[0]
        N = y.shape[1]

        y_hat = self.model(x)

        loss = F.cross_entropy(y_hat.view(-1, 2), y.view(-1), weight=self.weight.to(y.device))
        acc = self.train_accuracy(y_hat.view(-1, 2), y.view(-1))
        center_acc = self.train_accuracy(self.get_middle_scan(y_hat, N), self.get_middle_scan(y, N))

        self.log("train_loss", loss, on_step=True, on_epoch=True, prog_bar=True, logger=True, batch_size=B)
        self.log("train_acc", acc, on_step=True, on_epoch=True, prog_bar=True, logger=True, batch_size=B)
        self.log("train_center_acc", center_acc, on_step=True, on_epoch=True, prog_bar=True, logger=True, batch_size=B)
        return loss

    def validation_step(self, batch, batch_idx):
        x, y = self.split_input(batch)
        B = y.shape[0]
        N = y.shape[1]

        y_hat = self.model(x)

        loss = F.cross_entropy(y_hat.view(-1, 2), y.view(-1), weight=self.weight.to(y.device))
        acc = self.val_accuracy(y_hat.view(-1, 2), y.view(-1))
        center_acc = self.val_accuracy(self.get_middle_scan(y_hat, N), self.get_middle_scan(y, N))

        self.log("val_loss", loss, on_step=False, on_epoch=True, prog_bar=True, logger=True, batch_size=B)
        self.log("val_acc", acc, on_step=False, on_epoch=True, prog_bar=True, logger=True, batch_size=B)
        self.log("val_center_acc", center_acc, on_step=False, on_epoch=True, prog_bar=True, logger=True, batch_size=B)

    def test_step(self, batch, batch_idx):
        x, y = self.split_input(batch)
        B = y.shape[0]
        N = y.shape[1]

        y_hat = self.model(x)

        loss = F.cross_entropy(y_hat, y, weight=self.weight.to(y.device))
        acc = self.test_accuracy(y_hat, y)
        center_acc = self.test_accuracy(self.get_middle_scan(y_hat, N), self.get_middle_scan(y, N))

        self.log("test_loss", loss, on_step=False, on_epoch=True, prog_bar=True, logger=True, batch_size=B)
        self.log("test_acc", acc, on_step=False, on_epoch=True, prog_bar=True, logger=True, batch_size=B)
        self.log("test_center_acc", center_acc, on_step=False, on_epoch=True, prog_bar=True, logger=True, batch_size=B)

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.model.parameters(), lr=self.learning_rate)
        return optimizer

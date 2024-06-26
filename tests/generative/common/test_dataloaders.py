"""Test functions for dataloaders."""

from pathlib import Path
import pytest

import numpy as np
from omegaconf import DictConfig
import tensorflow as tf

from generative.common.constants import Normalisation, DataSplits
from generative.common.dataloaders import (
    get_dataset_from_file,
    get_dataset_from_folder,
    add_channel_dim,
    normalise,
    resize_dataset,
)


@pytest.mark.parametrize(
    "data_dims,expected_dims",
    [
        ([8, 4, 4], [8, 4, 4, 1]),
        ([8, 4, 4, 1], [8, 4, 4, 1]),
        ([8, 4, 4, 3], [8, 4, 4, 3]),
    ],
)
def test_add_channel_dim(data_dims: list[int], expected_dims: list[int]) -> None:
    """Test adding channel dimension."""
    dataset = np.zeros(data_dims)
    dataset = add_channel_dim(dataset)

    assert list(dataset.shape) == expected_dims


@pytest.mark.parametrize("data_dims", [[4, 4], [1, 4, 4, 2, 1]])
def test_add_channel_dim_fail(data_dims: list[int]) -> None:
    """Test channel dimension failure cases."""
    dataset = np.zeros(data_dims)

    with pytest.raises(ValueError):
        _ = add_channel_dim(dataset)


@pytest.mark.parametrize(
    "normalisation,expected_min_max",
    [
        (Normalisation.ZERO_ONE, [0.0, 1.0]),
        (Normalisation.NEG_ONE_ONE, [-1.0, 1.0]),
    ],
)
def test_normalise(normalisation: str, expected_min_max: list[float]) -> None:
    """Test normalisation."""
    dataset = np.repeat(np.reshape(np.arange(0, 256), [4, 8, 8, 1]), 3, axis=3)
    dataset = normalise(normalisation, dataset)

    assert np.isclose(dataset.min(), expected_min_max[0])
    assert np.isclose(dataset.max(), expected_min_max[1])


@pytest.mark.parametrize(
    "data_dims,expected_dims",
    [
        ([2, 4, 4, 1], [2, 8, 8, 1]),
        ([2, 4, 4, 1], [2, 16, 16, 1]),
        ([2, 4, 4, 3], [2, 8, 8, 3]),
        ([2, 4, 4, 3], [2, 16, 16, 3]),
    ],
)
def test_resize_dataset(data_dims: list[int], expected_dims: list[int]) -> None:
    """Test resizing dataset."""
    dataset = tf.zeros(data_dims)
    dataset = resize_dataset(expected_dims[1:3], dataset)

    assert list(dataset.shape) == expected_dims


@pytest.mark.parametrize("expected_dims", [[4], [4, 4, 1], [2, 4, 4, 3]])
def test_resize_dataset_fail(expected_dims: list[int]) -> None:
    """Test resizing dataset failure cases."""
    dataset = tf.zeros([2, 4, 4, 3])

    with pytest.raises(ValueError):
        _ = resize_dataset(expected_dims, dataset)


@pytest.mark.parametrize(
    "img_dims,normalisation,batch_size",
    [
        ([4, 4], Normalisation.ZERO_ONE, 2),
        ([4, 4], Normalisation.NEG_ONE_ONE, 4),
        ([8, 8], Normalisation.ZERO_ONE, 2),
        ([8, 8], Normalisation.NEG_ONE_ONE, 4),
    ],
)
def test_get_dataset_from_file(
    create_test_dataset_file: Path,
    img_dims: list[int],
    normalisation: str,
    batch_size: int,
) -> None:
    """Test loading dataset from file."""
    cfg = DictConfig(
        {
            "img_dims": img_dims,
            "normalisation": normalisation,
            "data_dir": create_test_dataset_file.parent,
            "dataset_name": "dataset",
            "batch_size": batch_size,
            "n_critic": 1,
        },
    )
    dataset = get_dataset_from_file(cfg, DataSplits.TRAIN)
    img_batch = next(iter(dataset))

    assert img_batch.ndim == 4
    assert img_batch.shape[0] == batch_size
    assert list(img_batch.shape)[1:3] == img_dims

    if normalisation == Normalisation.NEG_ONE_ONE:
        assert tf.reduce_min(img_batch) == -1.0
    else:
        assert tf.reduce_min(img_batch) == 0.0
    assert tf.reduce_max(img_batch) == 1.0


@pytest.mark.parametrize(
    "img_dims,normalisation,batch_size",
    [
        ([4, 4], Normalisation.ZERO_ONE, 2),
        ([4, 4], Normalisation.NEG_ONE_ONE, 4),
        ([8, 8], Normalisation.ZERO_ONE, 2),
        ([8, 8], Normalisation.NEG_ONE_ONE, 4),
    ],
)
def test_get_dataset_from_folder(
    create_test_dataset_folder: Path,
    img_dims: list[int],
    normalisation: str,
    batch_size: int,
) -> None:
    """Test loading dataset from folder."""
    cfg = DictConfig(
        {
            "img_dims": img_dims,
            "normalisation": normalisation,
            "data_dir": create_test_dataset_folder,
            "dataset_name": "dataset",
            "batch_size": batch_size,
            "n_critic": 1,
        },
    )
    dataset = get_dataset_from_folder(cfg)
    img_batch = next(iter(dataset))

    assert img_batch.ndim == 4
    assert img_batch.shape[0] == batch_size
    assert list(img_batch.shape)[1:3] == img_dims

    if normalisation == Normalisation.NEG_ONE_ONE:
        assert tf.reduce_min(img_batch) == -1.0
    else:
        assert tf.reduce_min(img_batch) == 0.0
    assert tf.reduce_max(img_batch) == 1.0


@pytest.mark.parametrize("batch_size,n_critic",[(1, 1), (2, 1), (1, 2), (2, 2)])
def test_get_dataset_from_file_ncritic(
    create_test_dataset_file: Path,
    batch_size: int,
    n_critic: int,
) -> None:
    """Test loading dataset from file with N_critic * batch size."""
    cfg = DictConfig(
        {
            "img_dims": [4, 4],
            "normalisation": Normalisation.NEG_ONE_ONE,
            "data_dir": create_test_dataset_file.parent,
            "dataset_name": "dataset",
            "batch_size": batch_size,
            "n_critic": n_critic,
        },
    )
    dataset = get_dataset_from_file(cfg, DataSplits.TRAIN, n_critic)
    img_batch = next(iter(dataset))

    assert img_batch.shape[0] == batch_size * n_critic


@pytest.mark.parametrize("batch_size,n_critic",[(1, 1), (2, 1), (1, 2), (2, 2)])
def test_get_dataset_from_folder_ncritic(
    create_test_dataset_folder: Path,
    batch_size: int,
    n_critic: int,
) -> None:
    """Test loading dataset from file with N_critic * batch size."""
    cfg = DictConfig(
        {
            "img_dims": [4, 4],
            "normalisation": Normalisation.NEG_ONE_ONE,
            "data_dir": create_test_dataset_folder,
            "dataset_name": "dataset",
            "batch_size": batch_size,
            "n_critic": n_critic,
        },
    )
    dataset = get_dataset_from_folder(cfg, n_critic)
    img_batch = next(iter(dataset))

    assert img_batch.shape[0] == batch_size * n_critic

"""Module defining Wasserstein discriminator training step mixins."""

import abc
import enum
from typing import Any

import tensorflow as tf
from omegaconf import DictConfig

from generative.common.logger import get_logger
from generative.common.losses import LossTypes

logger = get_logger(__file__)

KERNEL = "kernel"


class WassersteinTypes(str, enum.Enum):
    """Wasserstein GAN constrant types."""

    CLIP_WEIGHTS = "clip_weights"
    GRADIENT_PENALTY = "gradient_penalty"

    def __str__(self) -> str:
        """Get string representation."""
        return self.value


class GANMetaclass(abc.ABCMeta):
    """Metaclass for GANs.

    Notes:
    ------
    This metaclass is used to dynamically add a mixin to GAN classes if
    Wasserstein training is required.

    If the 'loss' argument is set to 'wasserstein', the WassersteinMixin
    overrides the discriminator_step method of the GAN class.
    """

    def __call__(cls, *args: DictConfig, **kwargs: DictConfig) -> Any:
        try:
            cfg = kwargs["cfg"]
        except KeyError:
            cfg = args[0]

        if cfg.loss == LossTypes.WASSERSTEIN:
            cls = type(f"Wasserstein{cls.__name__}", (WassersteinMixin, cls), {})  # type: ignore[assignment]
            logger.info("Using %s", WassersteinMixin.__name__)

        return super().__call__(*args, **kwargs)


class WeightClipConstraint(tf.keras.constraints.Constraint):
    """Clip weights in original Wasserstein GAN discriminator.

    Notes:
    -----
    Arjovsky et al. Wasserstein generative adversarial networks. ICML, 2017.
    https://arxiv.org/abs/1701.07875

    Args:
    ----
    clip_val: value to be clipped to (+/- clip-val)"""

    def __init__(self, clip_value: float) -> None:
        self._clip_value = clip_value

    def __call__(self, weights: tf.Tensor) -> tf.Tensor:
        return tf.clip_by_value(weights, -self._clip_value, self._clip_value)

    def get_config(self) -> dict[str, float]:
        return {"clip_value": self._clip_value}


class WassersteinMixin:
    """Mixin for adding Wasserstein GAN functionality.

    Notes:
    -----
    This mixin is added conditionally using the above
    metaclass  when the Wasserstein loss is selected in
    the config. Specifically the discriminator training
    step is overloaded.

    Args:
    ----
    cfg: config
    """

    discriminator: tf.keras.layers.Layer
    generator: tf.keras.layers.Layer
    _d_optimiser: tf.keras.optimizers.Optimizer
    _g_optimiser: tf.keras.optimizers.Optimizer
    _d_metric: tf.keras.metrics.Metric
    _latent_dim: int
    _loss: tf.keras.losses.Loss
    _mb_size: int

    def __init__(self, cfg: DictConfig):
        super().__init__(cfg)  # type: ignore[call-arg]
        self._n_critic = cfg.n_critic
        self._gradient_penalty_coeff = None

        if cfg.wasserstein_type == WassersteinTypes.CLIP_WEIGHTS:
            constraint = WeightClipConstraint(cfg.clip_value)
            logger.info("Using weight clipping: %s", cfg.clip_value)

            # Override discriminator already built by subclass
            self.build_discriminator(cfg, constraint=constraint)  # type: ignore[attr-defined]

        elif cfg.wasserstein_type == WassersteinTypes.GRADIENT_PENALTY:
            self._drift_term_coeff = cfg.get("drift_term", 0.0)
            self._gradient_penalty_coeff = cfg.gradient_penalty
            logger.info("Using gradient penalty: %s", cfg.gradient_penalty)

    def discriminator_step(self, real_images: tf.Tensor) -> None:
        """WGAN/WGAN-GP Discriminator training step.

        Args:
        ----
        real_images: tensor of real images
        """

        # Critic training loop
        for idx in range(self._n_critic):
            # Select minibatch of real images and generate fake images
            real_batch = real_images[
                idx * self._mb_size : (idx + 1) * self._mb_size,
                :,
                :,
                :,
            ]
            real_mb_size = tf.shape(real_batch)[0]

            if real_mb_size == 0:
                continue

            latent_noise = tf.random.normal(
                (real_mb_size, self._latent_dim),
                dtype="float32",
            )
            fake_images = self.generator(latent_noise, training=True)
            input_batch = tf.concat([real_batch, fake_images], axis=0)

            # Get gradients from critic predictions and update weights
            with tf.GradientTape() as tape:
                pred = self.discriminator(input_batch, training=True)
                loss = self._loss(
                    real=pred[0:real_mb_size, ...],
                    fake=pred[real_mb_size:, ...],
                )

                # Gradient penalty if indicated
                if self._gradient_penalty_coeff:
                    loss += self.apply_gradient_penalty(real_batch, fake_images)

            grads = tape.gradient(loss, self.discriminator.trainable_variables)
            self._d_optimiser.apply_gradients(
                zip(grads, self.discriminator.trainable_variables),
            )

            # Update metrics
            self._d_metric.update_state(loss)

    def apply_gradient_penalty(
        self,
        real_images: tf.Tensor,
        fake_images: tf.Tensor,
    ) -> tf.Tensor:
        """Apply gradient penalty from WGAN-GP.

        Notes:
        -----
        Gulrajani et al. Improved training of Wasserstein GANs. NeurIPS, 2017.
        https://arxiv.org/abs/1704.00028

        Args:
        ----
        real_images: tensor of real images
        fake_images: tensor of fake images

        """
        # Prevents discriminator output from drifting too far from zero (Progressive GAN)
        drift_term = tf.reduce_mean(tf.square(self.discriminator(real_images)))

        # Calculate random weighting of real and fake images
        epsilon = tf.random.uniform([tf.shape(fake_images)[0], 1, 1, 1], 0.0, 1.0)
        x_hat = epsilon * real_images + (1 - epsilon) * fake_images

        # Get discriminator output from real/fake images
        with tf.GradientTape() as tape:
            tape.watch(x_hat)
            D_hat = self.discriminator(x_hat, training=True)

        # Calculate gradients of output w.r.t. real/fake images
        gradients = tape.gradient(D_hat, x_hat)
        grad_penalty = self.calc_gradient_penalty(gradients)

        return (
            self._gradient_penalty_coeff * grad_penalty
            + self._drift_term_coeff * drift_term
        )

    def calc_gradient_penalty(self, gradients: tf.Tensor) -> tf.Tensor:
        grad_norm = tf.sqrt(tf.reduce_sum(tf.square(gradients), axis=[1, 2, 3]) + 1e-8)
        grad_penalty = tf.reduce_mean(tf.square(grad_norm - 1))

        return grad_penalty

    @property
    def n_critic(self) -> int:
        return int(self._n_critic)

    @property
    def gradient_penalty(self) -> int | float | None:
        return self._gradient_penalty_coeff

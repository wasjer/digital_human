import logging

logger = logging.getLogger("weight_engine")


class WeightEngine:

    def compute_decay(self, event: dict, days_elapsed: int, decay_config: dict) -> float:
        """
        importance 调制衰减公式：
          effective_rate = base_decay_rate ^ (1 - importance × damping_factor)
          new_decay_score = decay_score × effective_rate ^ days_elapsed

        重要事件衰减慢（effective_rate 接近 1），不重要事件衰减快。
        所有参数从 decay_config 读取（对应 global_state.decay_config 字段）。
        """
        base_rate     = float(decay_config.get("DECAY_BASE_RATE", 0.95))
        damping       = float(decay_config.get("DECAY_DAMPING_FACTOR", 0.6))
        importance    = float(event.get("importance", 0.0))
        decay_score   = float(event.get("decay_score", 1.0))

        effective_rate = base_rate ** (1.0 - importance * damping)
        new_decay_score = decay_score * (effective_rate ** days_elapsed)

        logger.debug(
            f"compute_decay event_id={event.get('event_id', '')[:8]} "
            f"importance={importance:.3f} days={days_elapsed} "
            f"effective_rate={effective_rate:.4f} "
            f"decay_score {decay_score:.4f} -> {new_decay_score:.4f}"
        )
        return new_decay_score

    def compute_emotion_gain(self, event: dict, emotion_signal) -> float:
        raise NotImplementedError("阶段二实现，等待数字身体模块")

    def compute_frequency_gain(self, event: dict) -> float:
        raise NotImplementedError("阶段二实现，基于 access_count")

    def compute_reflection_modulation(self, event: dict, reflection) -> float:
        raise NotImplementedError("阶段二实现")

    def update_weight(self, event: dict, decay_config: dict) -> float:
        """
        阶段一：只调用 compute_decay，days_elapsed 由调用方传入的 event 中读取。
        阶段二组合 emotion_gain / frequency_gain / reflection_modulation。
        """
        days_elapsed = int(event.get("_days_elapsed", 0))
        return self.compute_decay(event, days_elapsed, decay_config)

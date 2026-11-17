from app.models import StreamOffer


def apply_shares(bindings: list[StreamOffer]) -> None:
    ordered = sorted(bindings, key=lambda item: item.position)
    for binding in ordered:
        if binding.status != "active":
            binding.share = 0

    active = [binding for binding in ordered if binding.status == "active"]
    pinned = [binding for binding in active if binding.pinned]
    pin_sum = sum(binding.share for binding in pinned)
    if pin_sum > 100:
        raise ValueError("Сумма запиненных долей больше 100")

    free = [binding for binding in active if not binding.pinned]
    if not free:
        return

    remainder = 100 - pin_sum
    base, extra = divmod(remainder, len(free))
    for index, binding in enumerate(free):
        binding.share = base + (1 if index < extra else 0)

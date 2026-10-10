"""CPU scheduling model only. Does not validate CUDA, CC or attestation."""
import struct

FAULTS = ("L1", "L2", "C1", "C2")


def simulate(packets, fault, active):
    if fault not in FAULTS or type(active) is not bool or len(packets) != 3:
        raise ValueError("Invalid scenario")
    # A/g1, A/g2 and B/g2 are already prepared before injection. The injector
    # selects execution operations, never a verdict or an observed-state record.
    device = {}
    events = {}
    operations = []

    def transfer(slot, packet, event):
        device[slot] = bytes(packet)
        events[event] = True
        operations.append("copy:" + event)

    def wait(event):
        if not events.get(event):
            raise ValueError("Unrecorded dependency")
        operations.append("wait:" + event)

    transfer("current", packets[0], "E1")
    if fault == "L1":
        if not active:
            transfer("current", packets[1], "E2")
        wait("E1" if active else "E2")
        pointer = "current"
    elif fault == "L2":
        transfer("snapshot1", packets[0], "snapshot1-ready")
        graph_pointer = "snapshot1"  # capture a value, not a Python variable
        transfer("snapshot2", packets[1], "E2")
        wait("E2")
        if not active:
            graph_pointer = "snapshot2"
            operations.append("graph-update")
        pointer = graph_pointer
        operations.append("graph-replay")
    elif fault == "C1":
        if not active:
            transfer("current", packets[1], "E2")
        wait("E1" if active else "E2")
        pointer = "current"
    else:
        transfer("current", packets[1], "E2")
        transfer("other", packets[2], "B2")
        wait("E2")
        wait("B2")
        pointer = "other" if active else "current"
    # Consumer operates on stored bytes; it has no access to fault or contract.
    consumed = list(struct.unpack("<19I", device[pointer]))
    accumulator = 0
    for word in consumed[3:]:
        accumulator = (accumulator + word) % (2 ** 32)
    operations.append("consume-completed")
    if fault == "L1" and active:
        transfer("current", packets[1], "E2")
    return {"backend": "cpu-model", "execution_status": "MODEL_SUCCESS",
            "consumed_words": consumed, "consumer_sum": accumulator,
            "operation_trace": operations}

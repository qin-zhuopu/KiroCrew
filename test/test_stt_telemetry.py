"""Stage timings and the quantized catalog rows.

Two halves of one result: the recorder is what made the local speech path's cost
measurable at all, and the quantized rows are the lever those measurements showed
was worth adding on a CPU-only build (``base-q8_0`` decodes ~1.6x faster than
``base`` for a byte-identical transcript at 45% of the download).

The recorder's tests use fabricated samples rather than real inference, so the
assertions do not depend on the speed of the machine running the suite.
"""

from __future__ import annotations

import pytest

from kiro_crew.stt import models, telemetry


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> telemetry.Recorder:
    """A fresh recorder in place of the process-wide one.

    Replaced through ``monkeypatch`` rather than by calling ``reset()`` on the real
    singleton: the recorder is module state, and a test that mutates it in place
    leaves its samples visible to whatever runs next in the same process.
    """
    fresh = telemetry.Recorder()
    monkeypatch.setattr(telemetry, "_recorder", fresh)
    return fresh


def _sample(
    kind: str, *, audio_ms: float, wall_ms: float, aborted: bool = False
) -> telemetry.DecodeSample:
    return telemetry.DecodeSample(
        kind=kind,
        audio_ms=audio_ms,
        wall_ms=wall_ms,
        rtf=wall_ms / audio_ms if audio_ms else 0.0,
        aborted=aborted,
    )


class TestRecorderHoldsNoContent:
    def test_a_sample_has_no_field_that_could_hold_a_transcript(self):
        """The privacy rule, pinned as a shape rather than as a promise.

        The recording API takes a duration and a kind, so a function that never
        receives the text cannot leak it. This asserts the field set, because the way
        content arrives in telemetry is by someone adding a field for it.
        """
        fields = set(telemetry.DecodeSample.__dataclass_fields__)
        assert fields == {"kind", "audio_ms", "wall_ms", "rtf", "queue_wait_ms", "aborted", "at"}
        load_fields = set(telemetry.LoadSample.__dataclass_fields__)
        assert load_fields == {"model", "size_bytes", "hash_ms", "load_ms", "first_decode_ms", "at"}

    def test_the_snapshot_is_json_safe_numbers_and_enums(self, recorder: telemetry.Recorder):
        recorder.record_hash("base", 110.0)
        recorder.record_load("base", 147_951_465, 90.0)
        recorder.record_decode(_sample(telemetry.KIND_FINAL, audio_ms=11_000, wall_ms=650))
        snapshot = recorder.snapshot()
        # The model name is a value the user chose in settings and already appears in
        # the status payload; everything else is a number.
        assert snapshot["last_load"]["model"] == "base"
        assert isinstance(snapshot["last_final"]["rtf"], float)
        assert snapshot["decodes"][0]["kind"] == telemetry.KIND_FINAL


class TestLoadEpisodesAreSplitByPhase:
    def test_hash_load_and_first_decode_are_reported_separately(self, recorder: telemetry.Recorder):
        """One total made a 5.5 s digest check look like a slow model.

        Measured on a 32-core aarch64 host, ``large-v3-turbo``'s cold start is
        ~19.5 s of which 5.48 s is the SHA-256 over 1.6 GB. Those have completely
        different remedies (a faster disk, versus a smaller model), so a single
        number is not an answer.
        """
        recorder.record_hash("large-v3-turbo", 5_480.0)
        recorder.record_load("large-v3-turbo", 1_624_555_275, 540.0)
        recorder.record_decode(_sample(telemetry.KIND_PREWARM, audio_ms=1_000, wall_ms=13_510))
        episode = recorder.snapshot()["last_load"]
        assert episode["hash_ms"] == 5_480.0
        assert episode["load_ms"] == 540.0
        # The graph allocation the first decode pays belongs to the cold start, not
        # to the utterance that happened to trigger it.
        assert episode["first_decode_ms"] == 13_510

    def test_a_later_decode_does_not_overwrite_the_first(self, recorder: telemetry.Recorder):
        recorder.record_hash("base", 110.0)
        recorder.record_load("base", 147_951_465, 90.0)
        recorder.record_decode(_sample(telemetry.KIND_PREWARM, audio_ms=1_000, wall_ms=570))
        recorder.record_decode(_sample(telemetry.KIND_FINAL, audio_ms=11_000, wall_ms=650))
        assert recorder.snapshot()["last_load"]["first_decode_ms"] == 570

    def test_a_hash_is_never_folded_into_another_model_s_load(self, recorder: telemetry.Recorder):
        """The 50x misattribution: verify one model, load a different one.

        ``_verified_on_disk`` records the hash BEFORE comparing the digest, so a
        failed verification leaves a pending hash with nothing to consume it, and
        nothing clears it when no load follows. The first version discarded the model
        argument entirely, so the next load of ANY model inherited that time --
        ``large-v3-turbo``'s 5.48 s reported against ``base``'s real ~110 ms.
        """
        recorder.record_hash("large-v3-turbo", 5_480.0)
        recorder.record_load("base", 147_951_465, 90.0)
        episode = recorder.snapshot()["last_load"]
        assert episode["model"] == "base"
        assert episode["hash_ms"] == 0.0, "another model's digest time was folded in"
        # The verification still counted: it happened, and the count is what says a
        # digest check is being paid at all.
        assert recorder.snapshot()["hashes"] == 1

    def test_only_the_prewarm_decode_is_read_as_the_graph_build(self, recorder: telemetry.Recorder):
        """An utterance's own decode must never be published as a load phase.

        A prewarm runs with ``superseding=True``, so a boot prewarm racing a
        pointer-down prewarm aborts; the aborted sample is skipped, and without this
        restriction the next non-aborted decode fills the field. If that is a 60 s
        utterance, a field documented as a 30-40 ms graph build reports a minute.
        """
        recorder.record_hash("base", 110.0)
        recorder.record_load("base", 147_951_465, 90.0)
        recorder.record_decode(
            _sample(telemetry.KIND_PREWARM, audio_ms=1_000, wall_ms=12, aborted=True)
        )
        recorder.record_decode(_sample(telemetry.KIND_FINAL, audio_ms=60_000, wall_ms=74_000))
        assert recorder.snapshot()["last_load"]["first_decode_ms"] == 0.0

    def test_an_aborted_decode_is_not_taken_as_the_first(self, recorder: telemetry.Recorder):
        """An aborted decode's wall time is a fraction of the graph cost.

        Attributing it to the load would under-report the cold start, which is the
        number a user is trying to explain.
        """
        recorder.record_hash("base", 110.0)
        recorder.record_load("base", 147_951_465, 90.0)
        recorder.record_decode(
            _sample(telemetry.KIND_PREWARM, audio_ms=1_000, wall_ms=12, aborted=True)
        )
        assert recorder.snapshot()["last_load"]["first_decode_ms"] == 0.0


class TestThePayloadCarriesNoWallClock:
    def test_a_stamp_of_when_someone_spoke_never_reaches_the_payload(
        self, recorder: telemetry.Recorder
    ):
        """``at`` orders the recorder's own samples; it is not for the wire.

        The module's stated contract is durations and counts, and an absolute
        wall-clock time is neither -- it says when a person was dictating, on a body
        served to the browser and pasted into bug reports. The list already expresses
        ordering by being in order, so the field buys the payload nothing.
        """
        recorder.record_hash("base", 110.0)
        recorder.record_load("base", 147_951_465, 90.0)
        recorder.record_decode(_sample(telemetry.KIND_FINAL, audio_ms=11_000, wall_ms=650))
        snapshot = recorder.snapshot()
        for body in (snapshot["last_load"], snapshot["last_final"], snapshot["decodes"][0]):
            assert "at" not in body
        # The sample itself still carries it, so this is an omission at the boundary
        # rather than a measurement nobody takes.
        assert recorder._decodes[-1].at > 0

    def test_every_other_measured_field_does_reach_the_payload(self, recorder: telemetry.Recorder):
        """The projection is a denylist, and this is why it has to stay one.

        A field added to a sample is a measurement, and a measurement that silently
        failed to reach the status endpoint is the exact failure this module exists to
        prevent -- so anything not named private must appear.
        """
        recorder.record_decode(_sample(telemetry.KIND_FINAL, audio_ms=11_000, wall_ms=650))
        body = recorder.snapshot()["last_final"]
        expected = set(telemetry.DecodeSample.__dataclass_fields__) - telemetry._PRIVATE_FIELDS
        assert set(body) == expected

    def test_a_missing_sample_is_none_rather_than_an_empty_body(self, recorder: telemetry.Recorder):
        snapshot = recorder.snapshot()
        assert snapshot["last_load"] is None
        assert snapshot["last_final"] is None
        assert snapshot["last_decode"] is None

    def test_history_is_bounded(self, recorder: telemetry.Recorder):
        for _ in range(telemetry._HISTORY * 3):
            recorder.record_decode(_sample(telemetry.KIND_PARTIAL, audio_ms=1_000, wall_ms=10))
        assert len(recorder.snapshot()["decodes"]) == telemetry._HISTORY


class TestQuantizedCatalogRows:
    def test_every_entry_is_pinned_to_a_full_digest_and_a_real_size(self):
        for model in models.CATALOG:
            assert len(model.sha256) == 64, model.name
            assert set(model.sha256) <= set("0123456789abcdef"), model.name
            assert model.size_bytes > 0, model.name

    def test_names_and_digests_are_unique(self):
        """A quantized build is a different artifact and must never share a row.

        Two entries with one digest, or one name, is how a user ends up running
        weights they did not choose while the picker shows the name they did.
        """
        names = [m.name for m in models.CATALOG]
        digests = [m.sha256 for m in models.CATALOG]
        assert len(set(names)) == len(names)
        assert len(set(digests)) == len(digests)

    def test_a_quantized_row_declares_its_format(self):
        quantized = {m.name: m.quantization for m in models.CATALOG if m.quantization}
        assert quantized == {"base-q8_0": "q8_0", "small-q5_1": "q5_1"}

    def test_full_precision_rows_declare_no_quantization(self):
        # The catalog is one row per size class, and two of the four are quantized
        # (`base-q8_0`, `small-q5_1`) because in those classes quantization buys
        # speed and download size at no measured accuracy cost. `base` and
        # `large-v3-turbo` are the full-precision rows.
        for name in ("base", "large-v3-turbo"):
            assert models.resolve(name).quantization == ""

    def test_a_quantized_name_resolves_to_its_own_row_not_to_the_full_model(self):
        """The trap this avoids: serving different bytes under a familiar name.

        ``base-q8_0`` has to be its own artifact with its own digest, because its
        accuracy differs from ``base``. Resolving it to ``base`` would make a
        performance report meaningless -- the model named in the status payload would
        not be the one that ran.
        """
        chosen = models.resolve("base-q8_0")
        assert chosen.name == "base-q8_0"
        assert chosen.filename == "ggml-base-q8_0.bin"
        assert chosen.sha256 != models.resolve("base").sha256

    def test_the_default_is_still_the_full_precision_base(self):
        """Pinned deliberately.

        One English sample established that ``base-q8_0`` decodes ~1.6x faster for a
        byte-identical transcript; it did not establish equal accuracy across the
        eleven languages this feature offers, and quantization costs accuracy on the
        hardest inputs first. Changing the default needs multilingual WER/CER, so
        until then the faster rows are opt-in and this test says so.
        """
        assert models.DEFAULT_MODEL == "base"
        assert models.resolve(models.DEFAULT_MODEL).quantization == ""

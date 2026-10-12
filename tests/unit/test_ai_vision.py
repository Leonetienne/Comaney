"""
Vision capability: the ai_vision_available flag logic and AIService refusing
images for a provider without vision while text keeps working.
Run with: venv/bin/pytest tests/unit/test_ai_vision.py -v
"""
import pytest

from budget.ai_availability import vision_available
from budget.ai_service import VISION_UNSUPPORTED_MESSAGE, AIVisionUnsupportedError
from tests.unit.ai_fakes import FakeProvider, make_service

GOOD = '{"result": "good", "items": [{"title": "Coffee"}]}'


@pytest.mark.parametrize("ai_available, supports, expected", [
    (True, True, True),
    (True, False, False),
    (False, True, False),
    (False, False, False),
])
def test_vision_flag(ai_available, supports, expected):
    assert vision_available(ai_available, supports) is expected


class TestAIServiceImages:

    def test_non_vision_provider_refuses_image_without_calling(self):
        provider = FakeProvider((GOOD, 1.0), vision=False)
        service = make_service(provider)
        with pytest.raises(AIVisionUnsupportedError, match="cannot read images"):
            service.prompt_express_expense_gen("system", "coffee", image_b64="aGk=", image_type="image/png")
        assert provider.requests == []
        assert service.last_usage is None

    def test_vision_provider_gets_the_image(self):
        provider = FakeProvider((GOOD, 1.0), vision=True)
        items = make_service(provider).prompt_express_expense_gen("system", "", image_b64="aGk=", image_type="image/png")
        assert items == [{"title": "Coffee"}]
        (request,) = provider.requests
        assert [(i.data_b64, i.media_type) for i in request.images] == [("aGk=", "image/png")]

    @pytest.mark.parametrize("vision", [True, False])
    def test_text_only_works_on_both(self, vision):
        provider = FakeProvider((GOOD, 1.0), vision=vision)
        assert make_service(provider).prompt_express_expense_gen("system", "coffee 3") == [{"title": "Coffee"}]
        assert provider.requests[0].images == []

    def test_message_is_the_form_error(self):
        assert VISION_UNSUPPORTED_MESSAGE == "The configured AI cannot read images."

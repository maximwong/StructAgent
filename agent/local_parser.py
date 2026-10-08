"""Complete local JSON boundary, independent of professional implementations."""
from copy import deepcopy
from core import ToolValidationError
from .parameter_parser import ParseResult


class LocalEnvelopeParser:
    def __init__(self,envelope,registry):
        self.envelope=deepcopy(envelope);self.registry=registry

    def parse(self,text,*,project_id,profile_name=None):
        try:
            if self.envelope['project_id']!=project_id:
                raise ValueError('Project mismatch.')
            self.registry.get(self.envelope['tool']).validate(self.envelope)
            return ParseResult('ready',envelope=deepcopy(self.envelope),
                               metadata={'source':'explicit_local_json','inferred_fields':[]})
        except ToolValidationError as exc:
            return ParseResult('invalid_input',errors=exc.errors)
        except (ValueError,KeyError,TypeError):
            return ParseResult('invalid_input',errors=[{'code':'invalid_local_request','message':'需要完整且一致的本地Envelope。','path':[]}])

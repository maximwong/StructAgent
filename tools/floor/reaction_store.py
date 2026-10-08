"""Immutable reaction references with source and semantic recomputation."""
from pathlib import Path
import re
from uuid import uuid4

from core import ToolResult
from core.json_data import loads_json
from core.persistence import write_json
from core.validation import make_validator,validate_json
from .design_adapter import canonical_hash

REACTION_REFERENCE={'type':'string','pattern':r'^floor-reactions-[0-9a-f]{32}$'}


class FloorReactionStore:
    def __init__(self,root,adapter,output_schema):
        self.root=Path(root).resolve();self.adapter=adapter
        self.validator=make_validator(output_schema)

    def _check(self,data,project_id):
        result=ToolResult(**data)
        if (not result.success or result.version!='1.0.0' or result.metadata.get('project_id')!=project_id
                or result.tool not in ('extract_floor_reactions','analyze_floor_wall_reactions')):
            raise ValueError('Successful matching-project reaction result required.')
        validate_json(result.result,self.validator)
        expected=self.adapter.analyze(result.result['input'],project_id=project_id,
                                     walls=result.tool=='analyze_floor_wall_reactions')
        if canonical_hash(expected)!=canonical_hash(result.result):
            raise ValueError('Reaction content differs from independently verified source analysis.')
        return result

    def save(self,result):
        data=result.to_dict();self._check(data,result.metadata['project_id'])
        ref='floor-reactions-'+uuid4().hex
        self.root.mkdir(parents=True,exist_ok=True)
        write_json(self.root/(ref+'.json'),{'checksum':canonical_hash(data),'reaction':data},exclusive=True)
        return ref

    def load(self,reference,*,project_id):
        if not isinstance(reference,str) or re.fullmatch(REACTION_REFERENCE['pattern'],reference) is None:
            raise ValueError('Invalid reaction reference.')
        payload=loads_json((self.root/(reference+'.json')).read_text(encoding='utf-8'))
        if set(payload)!={'checksum','reaction'} or canonical_hash(payload['reaction'])!=payload['checksum']:
            raise ValueError('Reaction snapshot integrity failed.')
        return self._check(payload['reaction'],project_id)

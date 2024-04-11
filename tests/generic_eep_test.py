import unittest
import inspect
from eltakobus.eep import *

class TestEEPs(unittest.TestCase):
    
    def get_all_eep_names(self) -> list[str]:
        subclasses = set()
        work = [EEP]
        while work:
            parent = work.pop()
            for child in parent.__subclasses__():
                if child not in subclasses:
                    subclasses.add(child)
                    work.append(child)
        return sorted(set([s.__name__.upper().replace('_','-') for s in subclasses if len(s.__name__) == 8 and s.__name__.count('_') == 2]))


    NOT_SUPPORTED_EEPS = ['A5-09-0C', 'A5-38-08']


    def test_auto_gen_of_eep(self):
        
        for eep_name in self.get_all_eep_names():

            if eep_name in self.NOT_SUPPORTED_EEPS:
                continue

            sender_eep:EEP = EEP.find(eep_name)
            data = {
                'id': 'FF-DD-CC-BB',
                'eep': eep_name,
                'command': 1,
                'identifier': 1 }

            sig = inspect.signature(sender_eep.__init__)
            eep_init_args = [param.name for param in sig.parameters.values() if param.kind == param.POSITIONAL_OR_KEYWORD]
            knargs = {filter_key:data[filter_key] for filter_key in eep_init_args if filter_key in data and filter_key != 'self'}
            
            uknargs = {filter_key:0 for filter_key in eep_init_args if filter_key not in data and filter_key != 'self'}
            
            eep_args = knargs
            eep_args.update(uknargs)
                
            eep:EEP = sender_eep(**eep_args)

            self.assertEqual(sender_eep, type(eep))





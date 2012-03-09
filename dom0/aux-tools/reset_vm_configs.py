#!/usr/bin/python2.6
from qubes.qubes import QubesVmCollection
import sys
def main():
    if len(sys.argv) != 2:
        print 'Usage: fixconf templatename'
        sys.exit(1)
    qvm_collection = QubesVmCollection()
    qvm_collection.lock_db_for_reading()
    qvm_collection.load()
    qvm_collection.unlock_db()
    templ = sys.argv[1]
    tvm = qvm_collection.get_vm_by_name(templ)
    if tvm is None:
        print 'Template', templ, 'does not exist'
        sys.exit(1)
    if not tvm.is_template():
        print templ, 'is not a template'
        sys.exit(1)
    for vm in qvm_collection.values():
        if vm.template is not None and vm.template.qid == tvm.qid:
            vm.create_config_file()
    
main()

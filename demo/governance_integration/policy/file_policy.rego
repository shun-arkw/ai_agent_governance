package file_governance

import rego.v1

default allow := false

allow if {
    input.action.type == "read_file"
}

allow if {
    input.action.type == "write_file"
    input.resource.name == "normal.txt"
}

allow if {
    input.action.type == "delete_file"
    input.resource.name == "normal.txt"
}

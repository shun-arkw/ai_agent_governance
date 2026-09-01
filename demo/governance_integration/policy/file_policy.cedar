permit(
    principal,
    action == Action::"read_file",
    resource
);

permit(
    principal,
    action == Action::"write_file",
    resource == File::"normal.txt"
);

permit(
    principal,
    action == Action::"delete_file",
    resource == File::"normal.txt"
);

forbid(
    principal,
    action == Action::"delete_file",
    resource == File::"important.txt"
);

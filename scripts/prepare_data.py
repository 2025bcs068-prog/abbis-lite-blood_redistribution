from abbis.data_pipeline import prepare_redistribution_data


if __name__ == "__main__":
    report = prepare_redistribution_data()
    print(
        "Prepared redistribution data: "
        f"{report['derived_inventory']['eligible_units']:,} eligible units; "
        "see reports/data_quality.md"
    )


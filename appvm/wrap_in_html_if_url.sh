wrap_in_html_if_url()
{
	case "$1" in
	*://*)
		FILE_ARGUMENT=$(mktemp)
		
		echo -n '<html><meta HTTP-EQUIV="REFRESH" content="0; url=' > $FILE_ARGUMENT
		echo -n "$1" >> $FILE_ARGUMENT
		echo '"></html>' >> $FILE_ARGUMENT
		;;
	*)
		FILE_ARGUMENT="$1"
		;;
	esac
}
	
		